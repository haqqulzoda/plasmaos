"""Read projections preserve ownership and avoid transferring full analysis evidence."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from app.api.endpoints import tenders
from app.services import tender_details as details
from app.schemas import tender_details as schemas


def analysis_context():
    user=SimpleNamespace(id=uuid4(),is_admin=False)
    profile=SimpleNamespace(id=uuid4(),user_id=user.id)
    parent=SimpleNamespace(id=uuid4(),override_seal=None)
    version=SimpleNamespace(version_number=2,analysis_language='en',created_at=datetime.now(timezone.utc),input_hash='stored-hash',evidence_snapshot={'evidence_validation':{'private':'not in summary'}},result_snapshot={
        'analysis_status':'completed','requirements':{'mapped_requirement_uuids':['source text']*500,'unmapped_custom_requirements':['source requirement']},
        'hybrid_compliance':{'total_requirements':501,'manual_review_count':2,'raw_evidence':'private evidence'},
        'evaluation':{'unmapped_requirements':[{}, {}, {}]},
        'coverage_metadata':{'coverage_status':'partial','internal_debug':'not in summary','source_document_coverage':{'coverage_status':'partial','documents':['large evidence']*500}},
    })
    db=MagicMock();db.execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:profile));db.commit=AsyncMock();db.flush=AsyncMock()
    return user,profile,parent,version,db


def test_dashboard_projection_keeps_counts_without_snapshot_or_evidence():
    user,profile,parent,version,db=analysis_context();tid=uuid4()
    with patch.object(tenders,'_ensure_tender_access',new=AsyncMock()) as access,patch.object(tenders,'get_owned_analysis_parent_for_tender',new=AsyncMock(return_value=parent)) as owned,patch.object(tenders,'require_latest_analysis_version',new=AsyncMock(return_value=version)) as latest:
        result=asyncio.run(tenders.get_latest_analysis(tid,current_user=user,db=db,summary_only=True))
    assert result['requirement_count']==501 and result['manual_review_count']==3
    assert result['coverage_metadata']['coverage_status']=='partial'
    assert result['analysis_id']==str(parent.id) and result['version_number']==2
    assert not {'requirements','evaluation','hybrid_compliance','evidence_validation','result_snapshot','evidence_snapshot','content_hash'} & result.keys()
    assert 'private evidence' not in str(result) and 'internal_debug' not in str(result)
    access.assert_awaited_once();assert owned.await_args.kwargs['user_id']==user.id
    assert latest.await_args.kwargs['company_profile_id']==profile.id
    db.commit.assert_not_awaited();db.flush.assert_not_awaited()


def test_summary_cannot_bypass_tender_authorization():
    user,_,_,_,db=analysis_context()
    with patch.object(tenders,'_ensure_tender_access',new=AsyncMock(side_effect=HTTPException(403,'denied'))):
        with pytest.raises(HTTPException) as error:asyncio.run(tenders.get_latest_analysis(uuid4(),current_user=user,db=db,summary_only=True))
    assert error.value.status_code==403;db.execute.assert_not_awaited()


def test_absent_profile_remains_no_analysis_instead_of_loading_another_tenant():
    user,_,_,_,db=analysis_context();db.execute.return_value=SimpleNamespace(scalar_one_or_none=lambda:None)
    with patch.object(tenders,'_ensure_tender_access',new=AsyncMock()),patch.object(tenders,'get_owned_analysis_parent_for_tender',new=AsyncMock()) as owned:
        result=asyncio.run(tenders.get_latest_analysis(uuid4(),current_user=user,db=db,summary_only=True))
    assert result['analysis_id'] is None;owned.assert_not_awaited()


def test_details_recommendation_is_single_bounded_owned_read():
    user_id=uuid4();tender=SimpleNamespace(id=uuid4());profile=SimpleNamespace(id=uuid4(),user_id=user_id)
    recommendation=SimpleNamespace(id=uuid4(),match_score=88,strategic_rationale='original rationale '*100,is_dismissed=True,created_at=datetime.now(timezone.utc))
    db=MagicMock();db.scalar=AsyncMock(side_effect=[profile,recommendation]);db.commit=AsyncMock();db.flush=AsyncMock()
    empty=lambda cls:cls(state='EMPTY')
    with patch.object(details,'_project_sections',new=AsyncMock(return_value=(empty(schemas.ProjectContextSection),empty(schemas.ProjectLeadershipSection)))),patch.object(details,'_documents_section',new=AsyncMock(return_value=empty(schemas.TenderDocumentsSection))),patch.object(details,'_private_sections',new=AsyncMock(return_value=tuple(empty(cls) for cls in [schemas.ComplianceSection,schemas.RequirementsSection,schemas.CompanyReadinessSection,schemas.PursuitSection,schemas.BidPreparationSection]))):
        result=asyncio.run(details.compose_tender_details(db,tender=tender,user_id=user_id,procurement_contacts=None))
    statement=db.scalar.await_args_list[-1].args[0].compile(dialect=postgresql.dialect())
    assert 'company_profiles.user_id' in str(statement) and user_id in statement.params.values()
    assert tender.id in statement.params.values() and 1 in statement.params.values() and 'LIMIT' in str(statement)
    assert result.recommendation.match_score==88 and result.recommendation.is_dismissed
    assert len(result.recommendation.rationale_summary)==280
    assert db.scalar.await_count==2;db.commit.assert_not_awaited();db.flush.assert_not_awaited()


def test_historical_requirement_list_projects_without_full_payload():
    user,profile,parent,version,db=analysis_context()
    version.result_snapshot['requirements']=[{'label':'Original requirement'}]*3
    version.result_snapshot['hybrid_compliance']={}
    with patch.object(tenders,'_ensure_tender_access',new=AsyncMock()),patch.object(tenders,'get_owned_analysis_parent_for_tender',new=AsyncMock(return_value=parent)),patch.object(tenders,'require_latest_analysis_version',new=AsyncMock(return_value=version)):
        result=asyncio.run(tenders.get_latest_analysis(uuid4(),current_user=user,db=db,summary_only=True))
    assert result['requirement_count']==3 and 'requirements' not in result
