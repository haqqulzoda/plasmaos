"""Synthetic demo records for scripts/demo/seed_demo.py (D3-04).

Every project, firm and expert here is invented for demonstrations. Clients are
described generically by the kind of public body and its financier; no record
claims a real contract. Expert names are deliberately fictional.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


ORGANIZATION_PREFIX = "Demo Consulting LLC — "
FIRM_NAME = "Demo Consulting LLC"

PROFILE: dict[str, Any] = {
    "director_name": "Sardor Demoev",
    "address": "Demo address: 1 Example Street, Mirzo Ulugbek district, Tashkent, Uzbekistan",
    "phone_contact": "+998 71 000 00 00",
    "inn": "000000000",
    "industry": "Engineering and consulting: energy, water, transport, urban development",
    "target_regions": ["Central Asia", "East Asia"],
    "target_countries": ["Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Mongolia"],
    "target_services": ["Consulting services", "Engineering design", "Construction supervision", "Feasibility studies"],
}

SELF_FIRM: dict[str, Any] = {
    "display_name": FIRM_NAME,
    "canonical_name": FIRM_NAME,
    "legal_name": "Demo Consulting LLC (synthetic)",
    "country": "Uzbekistan",
    "regions": ["Central Asia", "Mongolia"],
    "services": ["Consulting services", "Engineering design", "Construction supervision", "Feasibility studies"],
    "capabilities": ["Transmission and substations", "Water supply and sanitation", "Roads", "Urban infrastructure"],
    "sectors": ["Energy", "Water", "Transport", "Urban development"],
    "evidence_state": "UNVERIFIED",
}


def _reference(
    name: str, client: str, country: str, sector: str, service: str, role: str, value: int | None,
    basis: str, start: str, end: str | None, scope: str, *, share: int | None = None, reviewed: bool = False,
) -> dict[str, Any]:
    return {
        "project_name": name, "client_name": client, "country": country, "sector": sector, "service": service,
        "role": role, "contract_share_percent": Decimal(share) if share is not None else None,
        "contract_value": Decimal(value) if value is not None else None, "contract_currency": "USD" if value is not None else None,
        "value_basis": basis if value is not None else "UNKNOWN",
        "start_date": date.fromisoformat(start), "completion_date": date.fromisoformat(end) if end else None,
        "completion_state": "COMPLETED" if end else "ONGOING", "relevant_scope": scope,
        "evidence_state": "REVIEWED" if reviewed else "UNVERIFIED",
    }


# 18 own references, 2012–2025; 6 REVIEWED.
OWN_REFERENCES: list[dict[str, Any]] = [
    _reference("Detailed design of three 220/110 kV substations, Fergana Valley", "Regional power grid PIU (World Bank-financed)",
               "Uzbekistan", "Energy", "Engineering design", "LEAD", 1_850_000, "CONTRACT_TOTAL", "2019-03-01", "2021-06-30",
               "Detailed engineering design, technical specifications and bidding documents for three 220/110 kV substations, "
               "including protection, SCADA integration and 110 kV line entries.", reviewed=True),
    _reference("Construction supervision of a 500 kV transmission line, southern Uzbekistan", "Transmission company PIU (ADB-financed)",
               "Uzbekistan", "Energy", "Construction supervision", "JV_MEMBER", 3_200_000, "CONSORTIUM_TOTAL", "2016-05-01", "2019-12-20",
               "Construction supervision of 210 km of 500 kV overhead line and two substation extensions as engineer under FIDIC.",
               share=40, reviewed=True),
    _reference("Feasibility study for 110 kV network rehabilitation, Khorezm region", "Regional electric networks company (World Bank-financed)",
               "Uzbekistan", "Energy", "Feasibility study", "LEAD", 620_000, "CONTRACT_TOTAL", "2022-02-01", "2023-05-31",
               "Load-flow studies, least-cost rehabilitation plan and economic analysis for 110 kV and 35 kV networks."),
    _reference("Owner's engineer for a 220 kV cross-border interconnection", "National grid operator PIU (EBRD-financed)",
               "Kyrgyzstan", "Energy", "Engineering design", "SUBCONSULTANT", 480_000, "FIRM_SHARE", "2020-09-01", "2023-03-31",
               "Design review of 220 kV line and substation works, factory acceptance tests and commissioning support.",
               share=25, reviewed=True),
    _reference("Substation automation and SCADA design, central energy system", "Energy regulatory PIU (ADB-financed)",
               "Mongolia", "Energy", "Engineering design", "SUBCONSULTANT", 390_000, "FIRM_SHARE", "2023-01-15", "2024-08-30",
               "Design of substation automation systems and SCADA upgrades for twelve 110 kV substations.", share=30),
    _reference("Water supply rehabilitation design, Bukhara city", "Municipal water utility PIU (World Bank-financed)",
               "Uzbekistan", "Water", "Engineering design", "LEAD", 1_100_000, "CONTRACT_TOTAL", "2017-04-01", "2019-02-28",
               "Hydraulic modelling, detailed design of 140 km of distribution mains, pumping stations and reservoirs.", reviewed=True),
    _reference("Construction supervision of water distribution networks, Samarkand", "Water supply agency PIU (AIIB-financed)",
               "Uzbekistan", "Water", "Construction supervision", "JV_MEMBER", 2_400_000, "CONSORTIUM_TOTAL", "2019-08-01", "2023-11-30",
               "Supervision of distribution network replacement and house connections for 300,000 residents.", share=50),
    _reference("Feasibility study for rural water supply, Karakalpakstan", "Rural water supply PIU (ADB-financed)",
               "Uzbekistan", "Water", "Feasibility study", "LEAD", 540_000, "CONTRACT_TOTAL", "2014-06-01", "2015-09-30",
               "Options analysis, groundwater assessment and preliminary design of group water supply schemes for 60 villages."),
    _reference("Wastewater treatment plant design, Khujand", "Municipal utility PIU (EBRD-financed)",
               "Tajikistan", "Water", "Engineering design", "SUBCONSULTANT", 310_000, "FIRM_SHARE", "2021-03-01", "2022-10-31",
               "Process and structural design of a 40,000 m3/day wastewater treatment plant.", share=35),
    _reference("Design review and supervision of water supply, Almaty region", "Regional water utility (EBRD-financed)",
               "Kazakhstan", "Water", "Construction supervision", "JV_MEMBER", 1_900_000, "CONSORTIUM_TOTAL", "2012-05-01", "2015-04-30",
               "Design review and site supervision of trunk mains, reservoirs and pumping stations.", share=35),
    _reference("Detailed design of a 4R regional road section (82 km)", "Road agency PIU (World Bank-financed)",
               "Uzbekistan", "Transport", "Engineering design", "LEAD", 1_350_000, "CONTRACT_TOTAL", "2018-01-15", "2019-10-31",
               "Topographic survey, pavement design, drainage and road safety design for an 82 km regional road.", reviewed=True),
    _reference("Construction supervision of an international road corridor section", "Road ministry PIU (ADB-financed)",
               "Kyrgyzstan", "Transport", "Construction supervision", "JV_MEMBER", 4_100_000, "CONSORTIUM_TOTAL", "2015-03-01", "2018-12-31",
               "Engineer's services for rehabilitation of 96 km of a two-lane international road.", share=30),
    _reference("Road safety audit and feasibility study, city bypass", "Transport ministry PIU (AIIB-financed)",
               "Tajikistan", "Transport", "Feasibility study", "SUBCONSULTANT", 260_000, "FIRM_SHARE", "2023-06-01", None,
               "Road safety audit, traffic surveys and feasibility of a 24 km urban bypass.", share=40),
    _reference("Urban street and lighting design, Tashkent districts", "City municipal infrastructure PIU (World Bank-financed)",
               "Uzbekistan", "Urban development", "Engineering design", "LEAD", 880_000, "CONTRACT_TOTAL", "2020-02-01", "2021-12-31",
               "Design of 45 km of urban streets, LED street lighting, sidewalks and stormwater drainage."),
    _reference("Design and supervision for medium-size cities urban development", "Urban development PIU (ADB-financed)",
               "Uzbekistan", "Urban development", "Construction supervision", "JV_MEMBER", 2_750_000, "CONSORTIUM_TOTAL", "2021-07-01", "2025-03-31",
               "Design review and supervision of urban roads, water, drainage and public spaces in three cities.", share=45),
    _reference("Ger-area infrastructure feasibility study, Ulaanbaatar", "Municipal PIU (ADB-financed)",
               "Mongolia", "Urban development", "Feasibility study", "SUBCONSULTANT", 350_000, "FIRM_SHARE", "2016-10-01", "2017-12-31",
               "Feasibility of water, heating and road networks for two ger-area sub-centres.", share=30),
    _reference("Grid connection studies for a 100 MW solar PV plant, Navoi", "Power transmission company (EBRD-financed)",
               "Uzbekistan", "Energy", "Feasibility study", "LEAD", 410_000, "CONTRACT_TOTAL", "2024-01-15", "2025-06-30",
               "Grid impact studies, 220 kV connection substation concept design and grid code compliance review.", reviewed=True),
    _reference("District heating network design, northern Kazakhstan", "Municipal heating utility (EBRD-financed)",
               "Kazakhstan", "Energy", "Engineering design", "SUBCONSULTANT", 290_000, "FIRM_SHARE", "2013-04-01", "2014-11-30",
               "Hydraulic analysis and detailed design of 18 km of pre-insulated district heating pipelines.", share=25),
]


def _partner_reference(name: str, client: str, country: str, sector: str, service: str, value: int, start: str, end: str, scope: str):
    return _reference(name, client, country, sector, service, "LEAD", value, "CONTRACT_TOTAL", start, end, scope)


# 6 partner firms with 3–5 references each. Names are invented.
PARTNERS: list[dict[str, Any]] = [
    {"display_name": "Kalvholm Transmission Engineering AB", "country": "Sweden", "services": ["Transmission line design", "Substation design"],
     "sectors": ["Energy"], "capabilities": ["400–500 kV design", "Protection and control"], "references": [
        _partner_reference("Design of a 400 kV interconnector", "Transmission system operator (EU-financed)", "Georgia", "Energy", "Engineering design",
                           2_600_000, "2017-02-01", "2019-08-31", "Detailed design of 160 km of 400 kV line and two substations."),
        _partner_reference("500 kV substation extension design", "Grid company PIU (World Bank-financed)", "Kazakhstan", "Energy", "Engineering design",
                           1_200_000, "2020-03-01", "2022-02-28", "Design of 500 kV bay extensions, protection and SCADA."),
        _partner_reference("Transmission master plan update", "Ministry of Energy PIU (ADB-financed)", "Mongolia", "Energy", "Feasibility study",
                           900_000, "2021-05-01", "2022-09-30", "Long-term transmission planning, load forecast and investment plan."),
        _partner_reference("Owner's engineer for a 220 kV ring", "Electricity company (EBRD-financed)", "Armenia", "Energy", "Construction supervision",
                           1_700_000, "2014-01-01", "2017-06-30", "Owner's engineer services for 220 kV ring network reinforcement."),
    ]},
    {"display_name": "Wesermark Wasserplan GmbH", "country": "Germany", "services": ["Water supply design", "Wastewater treatment"],
     "sectors": ["Water"], "capabilities": ["Hydraulic modelling", "Treatment process design"], "references": [
        _partner_reference("Water and wastewater master plan", "Municipal utility (KfW-financed)", "Kyrgyzstan", "Water", "Feasibility study",
                           1_400_000, "2016-04-01", "2018-03-31", "City-wide master plan for water and wastewater services."),
        _partner_reference("Wastewater treatment plant upgrade design", "Water utility PIU (EBRD-financed)", "Kazakhstan", "Water", "Engineering design",
                           2_100_000, "2019-01-15", "2021-07-31", "Design of biological treatment upgrade for 120,000 m3/day."),
        _partner_reference("Non-revenue water reduction programme", "Water supply company (World Bank-financed)", "Uzbekistan", "Water", "Consulting services",
                           1_050_000, "2022-02-01", "2024-12-31", "District metered areas, leak detection and utility performance contract design."),
    ]},
    {"display_name": "Dala Geo Survey LLP", "country": "Kazakhstan", "services": ["Topographic survey", "Geotechnical investigation"],
     "sectors": ["Transport", "Energy", "Water"], "capabilities": ["LiDAR survey", "Drilling and laboratory testing"], "references": [
        _partner_reference("Topographic and geotechnical survey for a 220 kV line", "Grid company (ADB-financed)", "Kazakhstan", "Energy", "Survey",
                           380_000, "2018-05-01", "2018-12-31", "LiDAR survey and geotechnical boreholes along 180 km route."),
        _partner_reference("Road corridor survey", "Road agency (World Bank-financed)", "Kazakhstan", "Transport", "Survey",
                           290_000, "2020-04-01", "2020-11-30", "Topographic survey and pavement investigations for 120 km."),
        _partner_reference("Dam safety geotechnical investigation", "Water resources committee (World Bank-financed)", "Kazakhstan", "Water", "Survey",
                           450_000, "2022-03-01", "2023-02-28", "Geotechnical investigation and instrumentation review for four dams."),
    ]},
    {"display_name": "Toroslar Yol Mühendislik A.Ş.", "country": "Türkiye", "services": ["Road design", "Construction supervision"],
     "sectors": ["Transport"], "capabilities": ["Highway design", "Bridges", "FIDIC supervision"], "references": [
        _partner_reference("Detailed design of an expressway section", "Highways directorate (World Bank-financed)", "Türkiye", "Transport", "Engineering design",
                           3_300_000, "2015-06-01", "2017-12-31", "Detailed design of 64 km dual carriageway with 12 bridges."),
        _partner_reference("Supervision of a regional road rehabilitation", "Road ministry PIU (ADB-financed)", "Tajikistan", "Transport", "Construction supervision",
                           2_800_000, "2018-02-01", "2021-10-31", "Engineer's services for 74 km regional road rehabilitation."),
        _partner_reference("Bridge rehabilitation design programme", "Road agency (EBRD-financed)", "Uzbekistan", "Transport", "Engineering design",
                           960_000, "2021-04-01", "2023-03-31", "Inspection and rehabilitation design of 28 bridges."),
        _partner_reference("Road asset management system", "Road fund (AIIB-financed)", "Georgia", "Transport", "Consulting services",
                           720_000, "2023-01-01", "2024-12-31", "Pavement management system and five-year maintenance programme."),
    ]},
    {"display_name": "Hanuri Mobility ITS Co., Ltd.", "country": "Republic of Korea", "services": ["Intelligent transport systems", "Traffic management"],
     "sectors": ["Transport", "Urban development"], "capabilities": ["ITS design", "Traffic control centres"], "references": [
        _partner_reference("Urban traffic management centre design", "City transport department (ADB-financed)", "Mongolia", "Urban development", "Engineering design",
                           1_150_000, "2017-03-01", "2019-06-30", "Design of adaptive signal control and a traffic management centre."),
        _partner_reference("Expressway ITS implementation supervision", "Road agency (World Bank-financed)", "Uzbekistan", "Transport", "Construction supervision",
                           1_600_000, "2020-05-01", "2023-04-30", "Supervision of tolling, variable message signs and incident detection."),
        _partner_reference("Public transport e-ticketing feasibility", "City administration (EBRD-financed)", "Kazakhstan", "Urban development", "Feasibility study",
                           420_000, "2022-07-01", "2023-06-30", "Feasibility and procurement strategy for e-ticketing."),
    ]},
    {"display_name": "Oqsuv Environmental LLC", "country": "Uzbekistan", "services": ["Environmental and social assessment", "Resettlement planning"],
     "sectors": ["Energy", "Water", "Transport", "Urban development"], "capabilities": ["ESIA", "ESMP", "RAP"], "references": [
        _partner_reference("ESIA for a 500 kV transmission line", "Transmission company (ADB-financed)", "Uzbekistan", "Energy", "Environmental assessment",
                           310_000, "2018-02-01", "2019-01-31", "Environmental and social impact assessment and ESMP."),
        _partner_reference("Resettlement action plan for urban roads", "Urban development PIU (World Bank-financed)", "Uzbekistan", "Urban development", "Social assessment",
                           180_000, "2020-06-01", "2021-03-31", "Census, asset inventory and resettlement action plan."),
        _partner_reference("Environmental monitoring of water supply works", "Water supply agency (AIIB-financed)", "Uzbekistan", "Water", "Environmental monitoring",
                           240_000, "2021-01-01", "2024-06-30", "ESMP compliance monitoring and quarterly reporting."),
        _partner_reference("Cumulative impact assessment for hydropower", "Energy ministry (World Bank-financed)", "Tajikistan", "Energy", "Environmental assessment",
                           420_000, "2016-09-01", "2018-05-31", "Basin-level cumulative impact assessment."),
        _partner_reference("ESMF for a rural infrastructure programme", "Rural development agency (World Bank-financed)", "Kyrgyzstan", "Urban development", "Environmental assessment",
                           150_000, "2023-02-01", "2023-10-31", "Environmental and social management framework."),
    ]},
]


def _expert(name: str, title: str, specializations: list[str], languages: list[str], degree: str, years: int,
            assignments: list[tuple[str, str, str, str, str]]) -> dict[str, Any]:
    return {
        "display_name": name, "qualifications": [degree, f"{years} years of professional experience"],
        "languages": languages, "specializations": [title, *specializations],
        "cv": {
            "education": [{"degree": degree}],
            "qualifications": [{"title": title, "years_experience": years}],
            "certifications": [],
            "assignments": [{"role": role, "project": project, "country": country, "start": start, "end": end}
                            for role, project, country, start, end in assignments],
            "languages": [{"language": language} for language in languages],
        },
    }


# 12 experts; names are clearly fictional.
EXPERTS: list[dict[str, Any]] = [
    _expert("Rustam Testov", "Team Leader / Power Systems Engineer", ["Transmission planning"], ["English", "Russian", "Uzbek"],
            "MSc Electrical Power Engineering", 22, [("Team Leader", "Detailed design of three 220/110 kV substations", "Uzbekistan", "2019-03", "2021-06"),
                                                      ("Power Systems Engineer", "500 kV transmission line supervision", "Uzbekistan", "2016-05", "2019-12")]),
    _expert("Dilnoza Sampleova", "Substation Design Engineer", ["Protection and control"], ["English", "Russian", "Uzbek"],
            "MSc Electrical Engineering", 14, [("Substation Engineer", "Grid connection studies, 100 MW solar PV", "Uzbekistan", "2024-01", "2025-06")]),
    _expert("Bekzod Mockhonov", "Transmission Line Engineer", ["Overhead line design"], ["Russian", "Uzbek"],
            "BSc Electrical Engineering", 12, [("Line Engineer", "220 kV cross-border interconnection", "Kyrgyzstan", "2020-09", "2023-03")]),
    _expert("Aigerim Fiktiva", "Water Supply Engineer", ["Distribution networks"], ["English", "Russian", "Kazakh"],
            "MSc Water Engineering", 16, [("Water Engineer", "Water supply rehabilitation design, Bukhara", "Uzbekistan", "2017-04", "2019-02")]),
    _expert("Jamshid Exampleov", "Hydraulic Modelling Specialist", ["EPANET", "Non-revenue water"], ["English", "Russian"],
            "MSc Hydraulic Engineering", 11, [("Hydraulic Modeller", "Samarkand water distribution supervision", "Uzbekistan", "2019-08", "2023-11")]),
    _expert("Malika Demova", "Road Design Engineer", ["Geometric design", "Road safety"], ["English", "Russian", "Uzbek"],
            "MSc Highway Engineering", 15, [("Road Design Engineer", "4R regional road design (82 km)", "Uzbekistan", "2018-01", "2019-10")]),
    _expert("Erlan Placeholdin", "Pavement Engineer", ["Pavement management"], ["Russian", "Kazakh"],
            "BSc Civil Engineering", 13, [("Pavement Engineer", "International road corridor supervision", "Kyrgyzstan", "2015-03", "2018-12")]),
    _expert("Gulnara Prototypova", "Resident Engineer", ["FIDIC contract administration"], ["English", "Russian", "Tajik"],
            "MSc Civil Engineering", 20, [("Resident Engineer", "Design and supervision for medium-size cities", "Uzbekistan", "2021-07", "2025-03")]),
    _expert("Sanjar Dummiev", "Environmental Specialist", ["ESIA", "ESMP"], ["English", "Russian", "Uzbek"],
            "MSc Environmental Science", 12, [("Environmental Specialist", "Urban street and lighting design", "Uzbekistan", "2020-02", "2021-12")]),
    _expert("Nodira Specimenova", "Social Safeguards Specialist", ["Resettlement", "Gender"], ["English", "Russian", "Uzbek"],
            "MA Sociology", 10, [("Social Specialist", "Rural water supply feasibility, Karakalpakstan", "Uzbekistan", "2014-06", "2015-09")]),
    _expert("Hans Beispielmann", "Procurement Specialist", ["World Bank procurement regulations"], ["English", "German", "Russian"],
            "MBA", 18, [("Procurement Specialist", "Wastewater treatment plant design, Khujand", "Tajikistan", "2021-03", "2022-10")]),
    _expert("Oyuna Zagvarova", "Urban Planner", ["Ger-area upgrading", "Land use"], ["English", "Mongolian", "Russian"],
            "MSc Urban Planning", 13, [("Urban Planner", "Ger-area infrastructure feasibility, Ulaanbaatar", "Mongolia", "2016-10", "2017-12")]),
]

# Words used to rank candidate notices by the demo firm's sectors.
SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "energy": ("transmission", "substation", "power", "electric", "grid", "energy", "heating"),
    "water": ("water", "wastewater", "sanitation", "irrigation"),
    "transport": ("road", "highway", "transport", "bridge", "railway"),
    "urban": ("urban", "city", "municipal"),
}
