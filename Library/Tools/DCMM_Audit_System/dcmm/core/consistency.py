"""Cross-file consistency checks — engine-agnostic pre-AI heuristics.

Detects template misuse, position title conflicts, strategy revision gaps,
and enterprise name variants before sending to the LLM.
"""

import re

# Industry keyword dictionary for cross-file template misuse detection
INDUSTRY_KEYWORDS = {
    '人力资源': ['人力资源', '劳务派遣', '人才寻访', '招聘服务', '人才测评', '人才派遣'],
    '通信': ['通信工程', '网络规划', '基站建设', '5G建设', '通信服务'],
    '能源': ['能源企业', '电力集团', '煤炭', '石油', '天然气', '发电', '电网'],
    '制造': ['生产线', '车间', '制造工艺', '精益生产'],
    '金融': ['银行', '证券', '保险', '基金管理'],
    '医疗': ['医院', '临床', '病历', '患者'],
    '交通': ['高速公路', '交通控股', '路桥', '收费站'],
}

REASONABLE_REF_PATTERNS = [
    '参考了', '借鉴', '对标', '学习了', '研究了', '梳理了',
    '标杆企业', '跨行业', '实践经验', '案例', '研讨',
    '等企业', '等行业', '等跨',
]

TEMPLATE_MISUSE_PATTERNS = [
    r'作为专注.*企业',
    r'核心业务覆盖',
    r'专注通信',
    r'专注.*工程服务',
    r'为建设.*能源企业',
    r'为建设.*提供坚实数据支撑',
    r'本公司是.*企业',
    r'我司是.*企业',
]


def classify_keyword_context(context: str, keyword: str) -> str:
    """Classify whether a keyword appearance is reasonable ref or template misuse."""
    if keyword in ['人力资源'] and any(
        x in context for x in
        ['人力资源部', '人力资源系', '人力资源上', '人力资源管', '人力资源部门', '人力资源与']
    ):
        return 'department'

    if any(x in context for x in ['深耕', '服务领域', '龙头企业', '所属行业', '经营范围', '助力企业']):
        return 'own_industry'

    for pattern in REASONABLE_REF_PATTERNS:
        if pattern in context:
            return 'reasonable_ref'

    for pattern in TEMPLATE_MISUSE_PATTERNS:
        if re.search(pattern, context):
            return 'suspected_misuse'

    return 'unclear'


def check_consistency(texts: dict, files: list, ent_name: str = '',
                       get_enterprise_inst=None) -> tuple:
    """Run automated cross-file consistency checks.

    Returns (findings: list[str], ent_industries: dict).
    get_enterprise_inst: optional callable to resolve assessment institution name.
    """
    findings = []
    ent_industries = {}

    # Check 1: Industry keyword consistency
    keyword_details = []
    for fname in files:
        text = texts.get(fname, '')
        found = []
        for ind, kws in INDUSTRY_KEYWORDS.items():
            for kw in kws:
                if kw in text:
                    for m in re.finditer(r'[\s\S]{30}' + re.escape(kw) + r'[\s\S]{30}', text):
                        ctx = m.group().replace('\n', ' ').strip()
                        classification = classify_keyword_context(ctx, kw)
                        found.append((ind, kw, classification, ctx[:80]))
                        break
                    break
        ent_industries[fname] = [(f[0], f[1]) for f in found]

        misuse_kws = [f for f in found if f[2] == 'suspected_misuse']
        if misuse_kws:
            detail_parts = [f'{ind}("{kw}"→确凿套用: {ctx[:60]})'
                            for ind, kw, _cls, ctx in misuse_kws]
            industries_str = ', '.join(set(f[0] for f in misuse_kws))
            findings.append(f'🔴 {fname}: 确凿模板套用 [{industries_str}] {"; ".join(detail_parts)}')

    # Check 2: Position title consistency
    titles = {}
    for fname in files:
        text = texts.get(fname, '')
        for title in ['部长', '主任', '组长']:
            for m in re.finditer(f'数据治理委员会.{title}', text):
                if fname not in titles:
                    titles[fname] = set()
                titles[fname].add(title)
    all_title_vals = set()
    for ts in titles.values():
        all_title_vals.update(ts)
    if len(all_title_vals) > 1:
        findings.append(f'⚠️ 职位名称矛盾: {dict(titles)}')

    # Check 3: Strategy revision
    revision_mentions = []
    for fname in files:
        text = texts.get(fname, '')
        for m in re.finditer(r'.{15}修订.{15}', text):
            ctx = m.group().replace('\n', ' ')
            if '战略' in ctx:
                revision_mentions.append(f'{fname}: ...{ctx}...')
    if len(revision_mentions) > 1:
        findings.append(f'⚠️ 战略修订表述不一致: {revision_mentions}')

    # Check 4: Enterprise name variants
    names = {}
    for fname in files:
        text = texts.get(fname, '')
        for m in re.finditer(r'[\u4e00-\u9fff]{2,8}(?:公司|有限公司|集团|医院)', text):
            name = m.group()
            if name not in names:
                names[name] = []
            names[name].append(fname)

    exclude_names = set()
    if ent_name:
        own_name = re.sub(r'^\d+、', '', ent_name)
        own_name = re.sub(r'[+\-]?[345]级[+\-]?[甲乙]方?', '', own_name).strip()
        if own_name:
            exclude_names.add(own_name)
        if get_enterprise_inst:
            inst = get_enterprise_inst(ent_name)
            if inst:
                exclude_names.add(inst)
                for sl in [4, 5, 6]:
                    if len(inst) > sl:
                        exclude_names.add(inst[:sl])

    variants = [
        n for n in names if ('公司' in n or '集团' in n) and len(n) > 4
        and not any(n in ex or ex in n for ex in exclude_names if len(ex) > 3)
    ]
    if len(variants) > 2:
        findings.append(f'ℹ️ 企业名称变体: {variants[:5]}')

    return findings, ent_industries
