"""
IRS 990 XML parser powered by irsx library.
Parses local XML files and inserts structured data into PostgreSQL.
"""

import os
import logging
from irsx.filing import Filing

from db import (
    upsert_organization, insert_filing, insert_grants,
    insert_compensation, insert_programs, insert_mission,
    filing_exists,
)

logger = logging.getLogger(__name__)


def as_list(x):
    """Normalise an irsx result to a list.

    irsx returns a single dict when a repeating group has one entry and a
    list of dicts when it has multiple. Iterating a dict yields its keys
    (strings), which then break `.get()` calls in the loop body. Wrap every
    repeating-group iteration with this helper.
    """
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x]
    return []


def deep_get(d, key):
    """Recursively search a nested dict/list for a key."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            result = deep_get(v, key)
            if result is not None:
                return result
    elif isinstance(d, list):
        for item in d:
            result = deep_get(item, key)
            if result is not None:
                return result
    return None


def _to_float(val):
    """Convert a string value to float, returning 0 if invalid."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(',', ''))
    except (ValueError, TypeError):
        return 0.0


def safe_str(val):
    """Convert a value to a trimmed string, handling nested dicts."""
    if val is None:
        return None
    if isinstance(val, dict):
        for v in val.values():
            if v:
                return str(v).strip()
        return None
    s = str(val).strip()
    return s if s else None


def derive_subsection(sked):
    """Derive IRS subsection code from 990 schedule indicators."""
    c3 = sked.get('Organization501c3Ind')
    c4947 = sked.get('Organization4947a1Ind')
    c_ind = sked.get('Organization501cInd')
    c_type = safe_str(sked.get('Organization501cTypeTxt'))

    if c3 and str(c3).upper() in ('X', '1', 'TRUE'):
        return '501(c)(3)'
    if c4947 and str(c4947).upper() in ('X', '1', 'TRUE'):
        return '4947(a)(1)'
    if c_ind and str(c_ind).upper() in ('X', '1', 'TRUE') and c_type:
        # c_type may be "3" or "501(c)(3)"
        digits = ''.join(ch for ch in c_type if ch.isdigit() or ch in '().-')
        if digits.startswith('501(c)'):
            return digits
        return f'501(c)({c_type})'
    if c_type:
        if c_type.startswith('501(c)'):
            return c_type
        return f'501(c)({c_type})'
    return None


def extract_name(person):
    """Try multiple name fields â€” PersonNm or BusinessName."""
    name = safe_str(person.get('PersonNm'))
    if name:
        return name
    name = safe_str(person.get('BusinessName'))
    return name


def parse_990(f, schedules):
    """Parse a standard IRS Form 990."""
    sked = f.get_schedule('IRS990')
    header = f.get_schedule('ReturnHeader990x')
    filer = header.get('Filer', {}) or {}
    addr = filer.get('USAddress', {}) or {}

    ein = f.get_ein()
    org_name = safe_str(filer.get('BusinessName'))
    tax_year = safe_str(header.get('TaxYr'))
    period_end = safe_str(header.get('TaxPeriodEndDt'))
    period_begin = safe_str(header.get('TaxPeriodBeginDt'))

    # Upsert organization
    subsection = derive_subsection(sked)
    upsert_organization(
        ein=ein, name=org_name,
        city=safe_str(addr.get('CityNm')),
        state=safe_str(addr.get('StateAbbreviationCd')),
        zip_code=safe_str(addr.get('ZIPCd')),
        street=safe_str(addr.get('AddressLine1Txt')),
        subsection=subsection,
        tax_year=int(tax_year) if tax_year else None,
        form_type='990',
    )

    # Build parsed_data for JSONB storage
    rev = safe_str(sked.get('CYTotalRevenueAmt'))
    exp = safe_str(sked.get('CYTotalExpensesAmt'))
    parsed = {
        'total_revenue': rev,
        'total_expenses': exp,
        'total_assets': safe_str(sked.get('TotalAssetsEOYAmt')),
        'total_liabilities': safe_str(sked.get('TotalLiabilitiesEOYAmt')),
        'net_assets': safe_str(sked.get('NetAssetsOrFundBalancesEOYAmt')),
        'contributions': safe_str(sked.get('CYContributionsGrantsAmt')),
        'prog_revenue': safe_str(sked.get('CYProgramServiceRevenueAmt')),
        'invest_income': safe_str(sked.get('CYInvestmentIncomeAmt')),
        'other_revenue': safe_str(sked.get('CYOtherRevenueAmt')),
        'grants_paid': safe_str(sked.get('CYGrantsAndSimilarPaidAmt')),
        'salaries': safe_str(sked.get('CYSalariesCompEmpBnftPaidAmt')),
        'fundraising_fees': safe_str(sked.get('CYTotalFundraisingExpenseAmt')),
    }
    try:
        parsed['net_income'] = str(int(rev) - int(exp)) if rev and exp else None
    except (ValueError, TypeError):
        parsed['net_income'] = None

    # Mission
    mission_raw = safe_str(sked.get('MissionDesc')) or ''
    mission_text = None
    programs_text = None

    if 'SCHEDULE O' in mission_raw.upper():
        sched_o = f.get_schedule('IRS990ScheduleO') if 'IRS990ScheduleO' in schedules else None
        mission_parts = []
        prog_parts = []
        if sched_o:
            for entry in as_list(sched_o.get('SupplementalInformationDetail')):
                ref = (entry.get('FormAndLineReferenceDesc') or '').lower()
                text = entry.get('ExplanationTxt') or ''
                if not text:
                    continue
                if 'mission' in ref or 'part i' in ref or 'line 1' in ref:
                    mission_parts.append(text)
                elif 'part iii' in ref or 'program service' in ref or 'program accomplishment' in ref:
                    prog_parts.append(text)
        mission_text = '\n\n'.join(mission_parts) if mission_parts else None
        programs_text = '\n\n'.join(prog_parts) if prog_parts else None
    else:
        mission_text = mission_raw if mission_raw else None
        prog_parts = []
        for grp in as_list(sked.get('ProgramServiceAccomplishmentGrp')):
            desc = safe_str(grp.get('DescriptionProgramServiceAccomTxt'))
            if desc:
                prog_parts.append(desc)
        programs_text = '\n\n'.join(prog_parts) if prog_parts else None

    parsed['mission'] = mission_text
    parsed['program_accomplishments'] = programs_text

    # Check Schedule D for donor-advised fund activity
    sched_d = f.get_schedule('IRS990ScheduleD') if 'IRS990ScheduleD' in schedules else None
    daf_activity = False
    if sched_d:
        daf_ind = safe_str(deep_get(sched_d, 'DonorAdvisedFundInd'))
        daf_cnt = safe_str(deep_get(sched_d, 'DonorAdvisedFundHeldCnt'))
        daf_activity = bool(daf_ind or daf_cnt)
    parsed['daf_activity'] = daf_activity

    # Received date from header
    received_date = safe_str(header.get('ReturnTs')) or safe_str(header.get('BuildTs'))

    # Insert filing
    object_id = f.object_id
    filing_id = insert_filing(
        ein=ein, object_id=object_id, tax_year=int(tax_year) if tax_year else None,
        form_type='990', period_begin=period_begin, period_end=period_end,
        received_date=received_date, raw_xml=f.raw_xml, parsed_data=parsed,
    )

    # Grants (Schedule I)
    sched_i = f.get_schedule('IRS990ScheduleI') if 'IRS990ScheduleI' in schedules else None
    grant_rows = []
    if sched_i:
        for r in as_list(sched_i.get('RecipientTable')):
            name = safe_str(r.get('RecipientBusinessName'))
            amt = safe_str(r.get('CashGrantAmt'))
            if name or amt:
                grant_rows.append({
                    'grantee': name,
                    'ein': safe_str(r.get('RecipientEIN')),
                    'amount': amt,
                    'purpose': safe_str(r.get('PurposeOfGrantTxt')),
                    'city': safe_str(r.get('USAddress', {}).get('CityNm')) if r.get('USAddress') else None,
                    'state': safe_str(r.get('USAddress', {}).get('StateAbbreviationCd')) if r.get('USAddress') else None,
                })
    insert_grants(filing_id, grant_rows)

    # Compensation
    comp_rows = []
    sched_j = f.get_schedule('IRS990ScheduleJ') if 'IRS990ScheduleJ' in schedules else None
    if sched_j:
        for p in as_list(sched_j.get('RltdOrgOfficerTrstKeyEmplGrp')):
            name = extract_name(p)
            if name:
                base = safe_str(p.get('BaseCompensationFilingOrgAmt'))
                bonus = safe_str(p.get('BonusFilingOrganizationAmount'))
                other = safe_str(p.get('OtherCompensationFilingOrgAmt'))
                related = safe_str(p.get('RelatedOrganizationCompAmt'))
                total = (_to_float(base) or 0) + (_to_float(bonus) or 0) + (_to_float(other) or 0) + (_to_float(related) or 0)
                comp_rows.append({
                    'name': name,
                    'title': safe_str(p.get('TitleTxt')),
                    'base': base,
                    'bonus': bonus,
                    'other': other,
                    'related': related,
                    'total': str(int(total)) if total else None,
                })
    if not comp_rows:
        for p in as_list(sked.get('Form990PartVIISectionAGrp')):
            name = extract_name(p)
            if name:
                base = safe_str(p.get('ReportableCompFromOrgAmt'))
                total = _to_float(base) or 0
                comp_rows.append({
                    'name': name,
                    'title': safe_str(p.get('TitleTxt')),
                    'base': base,
                    'bonus': None,
                    'other': None,
                    'total': str(int(total)) if total else None,
                })
    insert_compensation(filing_id, comp_rows)

    # Programs + Mission
    insert_programs(filing_id, programs_text)
    insert_mission(filing_id, mission_text)

    return {
        'ein': ein, 'org_name': org_name, 'tax_year': tax_year,
        'form_type': '990', 'grants': len(grant_rows), 'comp': len(comp_rows),
        'mission': bool(mission_text),
    }


def parse_990pf(f, schedules):
    """Parse IRS Form 990-PF."""
    sked = f.get_schedule('IRS990PF')
    header = f.get_schedule('ReturnHeader990x')
    filer = header.get('Filer', {}) or {}
    addr = filer.get('USAddress', {}) or {}

    ein = f.get_ein()
    org_name = safe_str(filer.get('BusinessName'))
    tax_year = safe_str(header.get('TaxYr'))
    period_end = safe_str(header.get('TaxPeriodEndDt'))
    period_begin = safe_str(header.get('TaxPeriodBeginDt'))

    upsert_organization(
        ein=ein, name=org_name,
        city=safe_str(addr.get('CityNm')),
        state=safe_str(addr.get('StateAbbreviationCd')),
        zip_code=safe_str(addr.get('ZIPCd')),
        street=safe_str(addr.get('AddressLine1Txt')),
        subsection='501(c)(3)',
        tax_year=int(tax_year) if tax_year else None,
        form_type='990PF',
    )

    rev = safe_str(deep_get(sked, 'TotalRevAndExpnssAmt'))
    exp = safe_str(deep_get(sked, 'TotOprExpensesRevAndExpnssAmt'))
    parsed = {
        'total_revenue': rev,
        'total_expenses': exp,
        'total_assets': safe_str(sked.get('FMVAssetsEOYAmt')),
        'total_liabilities': safe_str(deep_get(sked, 'TotalLiabilitiesEOYAmt')),
        'net_assets': safe_str(deep_get(sked, 'TotNetAstOrFundBalancesEOYAmt')),
        'invest_income': safe_str(deep_get(sked, 'TotalNetInvstIncmAmt')),
        'salaries': safe_str(deep_get(sked, 'CompOfcrDirTrstRevAndExpnssAmt')),
        'grants_paid': safe_str(deep_get(sked, 'TotalGrantOrContriPdDurYrAmt')),
        'net_income': safe_str(deep_get(sked, 'ExcessRevenueOverExpensesAmt')),
        'contributions': None,
        'prog_revenue': None,
        'fundraising_fees': None,
    }

    mission_text = safe_str(deep_get(sked, 'MissionDscriptionOrSignificantActyTxt'))
    if not mission_text:
        mission_text = 'Private operating foundation â€” see Form 990-PF for charitable purpose statement'
    parsed['mission'] = mission_text
    parsed['program_accomplishments'] = None

    received_date = safe_str(header.get('ReturnTs')) or safe_str(header.get('BuildTs'))
    object_id = f.object_id
    filing_id = insert_filing(
        ein=ein, object_id=object_id, tax_year=int(tax_year) if tax_year else None,
        form_type='990PF', period_begin=period_begin, period_end=period_end,
        received_date=received_date, raw_xml=f.raw_xml, parsed_data=parsed,
    )

    # Grants
    grant_rows = []
    for g in as_list(deep_get(sked, 'GrantOrContributionPdDurYrGrp')):
        name = safe_str(g.get('RecipientBusinessName'))
        amt = safe_str(g.get('Amt'))
        if amt:
            grant_rows.append({
                'grantee': name or 'Various grantees',
                'ein': safe_str(g.get('RecipientEIN')),
                'amount': amt,
                'purpose': safe_str(g.get('GrantOrContributionPurposeTxt')),
                'city': None,
                'state': None,
            })
    insert_grants(filing_id, grant_rows)

    # Compensation
    comp_rows = []
    for p in as_list(deep_get(sked, 'OfficerDirTrstKeyEmplGrp')):
        name = extract_name(p)
        if name:
            base = safe_str(p.get('CompensationAmt'))
            total = _to_float(base) or 0
            comp_rows.append({
                'name': name,
                'title': safe_str(p.get('TitleTxt')),
                'base': base,
                'bonus': None,
                'other': None,
                'total': str(int(total)) if total else None,
            })
    insert_compensation(filing_id, comp_rows)

    insert_mission(filing_id, mission_text)

    return {
        'ein': ein, 'org_name': org_name, 'tax_year': tax_year,
        'form_type': '990PF', 'grants': len(grant_rows), 'comp': len(comp_rows),
        'mission': bool(mission_text),
    }


def parse_file(filepath, min_file_size=20000):
    """Parse a single IRS XML file and store in database."""
    if os.path.getsize(filepath) < min_file_size:
        return {'skip': True, 'reason': 'File too small â€” likely 990-N stub'}

    fname = os.path.basename(filepath)
    object_id = os.path.splitext(fname)[0]

    if filing_exists(object_id):
        return {'skip': True, 'reason': 'Already in database'}

    with open(filepath, 'r', encoding='utf-8', errors='replace') as xf:
        raw_xml = xf.read()

    try:
        f = Filing(object_id, filepath=filepath)
        f.process()
        f.raw_xml = raw_xml
    except Exception as e:
        logger.error(f"Parse error for {filepath}: {e}")
        return {'skip': True, 'reason': f'Parse error: {e}'}

    schedules = f.list_schedules()

    if 'IRS990' not in schedules and 'IRS990PF' not in schedules:
        return {'skip': True, 'reason': 'Unsupported form type'}

    if 'IRS990PF' in schedules:
        return parse_990pf(f, schedules)
    else:
        return parse_990(f, schedules)


