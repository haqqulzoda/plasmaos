export type ProjectSourceFreshness =
    | 'fresh'
    | 'stale'
    | 'incomplete'
    | 'unavailable'
    | 'pending';

export type ProjectCanonicalRole =
    | 'TASK_TEAM_LEADER'
    | 'CO_TASK_TEAM_LEADER'
    | 'PROJECT_TASK_MANAGER'
    | 'OTHER_PROJECT_ROLE'
    | string;

export interface ProjectContextRole {
    role_type: 'PROJECT_LEADERSHIP';
    source_system: string;
    display_name: string;
    native_role: string;
    canonical_role: ProjectCanonicalRole;
    email: string | null;
    phone: string | null;
    source_url: string | null;
    first_observed_at: string;
    last_observed_at: string;
    ended_at: string | null;
}

export interface ProjectContextProject {
    id: string;
    source_system: string;
    external_project_id: string;
    name: string | null;
    country: string | null;
    region: string | null;
    status: string | null;
    approval_date: string | null;
    closing_date: string | null;
    borrower: string | null;
    implementing_agencies: string[] | null;
    source_url: string | null;
    enrichment_status: string;
    last_successful_enrichment_at: string | null;
    source_freshness: ProjectSourceFreshness;
}

export interface TenderProjectContext {
    project: ProjectContextProject;
    current_roles: ProjectContextRole[];
    historical_roles: ProjectContextRole[];
}

export interface ProjectMetadataRow {
    label: string;
    value: string;
}

export type ProjectContextFailureKind =
    | 'no_project'
    | 'authorization'
    | 'endpoint_failure';

export const classifyProjectContextFailure = (status?: number): ProjectContextFailureKind => {
    if (status === 404) return 'no_project';
    if (status === 401 || status === 403) return 'authorization';
    return 'endpoint_failure';
};

export const projectRoleLabel = (
    role: Pick<ProjectContextRole, 'canonical_role' | 'native_role' | 'source_system'>,
    sourceDisplayName = 'Official project source',
) => {
    // Defense in depth: this technical Projects API field never claims TTL semantics.
    if (role.native_role.trim().toLowerCase() === 'teamleadname') {
        return `${sourceDisplayName} project team`;
    }
    if (role.canonical_role === 'TASK_TEAM_LEADER') return 'Task Team Leader';
    if (role.canonical_role === 'CO_TASK_TEAM_LEADER') return 'Co-Task Team Leader';
    if (role.canonical_role === 'PROJECT_TASK_MANAGER') return 'Task Manager';
    if (role.canonical_role === 'OTHER_PROJECT_ROLE') {
        return `${sourceDisplayName} project team`;
    }
    return 'Project role';
};

export const projectFreshnessMessage = (freshness: ProjectSourceFreshness) => {
    if (freshness === 'stale') return 'Project information may be outdated.';
    if (freshness === 'incomplete') return 'Some project information is unavailable.';
    if (freshness === 'unavailable') return 'Official project data is currently unavailable.';
    if (freshness === 'pending') return 'Project details are being prepared.';
    return null;
};

export const formatProjectDate = (value?: string | null) => {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        timeZone: 'UTC',
    });
};

export const projectMetadataRows = (project: ProjectContextProject): ProjectMetadataRow[] => {
    const rows: ProjectMetadataRow[] = [];
    const geography = [project.country, project.region].filter(Boolean).join(' / ');
    const approvalDate = formatProjectDate(project.approval_date);
    const closingDate = formatProjectDate(project.closing_date);
    const agencies = (project.implementing_agencies ?? []).filter((agency) => agency.trim()).join(', ');

    if (geography) rows.push({ label: 'Country / Region', value: geography });
    if (project.status?.trim()) rows.push({ label: 'Project Status', value: project.status });
    if (approvalDate) rows.push({ label: 'Project Approval', value: approvalDate });
    if (closingDate) rows.push({ label: 'Project Closing', value: closingDate });
    if (project.borrower?.trim()) rows.push({ label: 'Borrower', value: project.borrower });
    if (agencies) rows.push({ label: 'Implementing Agency', value: agencies });
    return rows;
};
