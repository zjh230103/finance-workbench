# -*- coding: utf-8 -*-
"""每日 09:00 抓取「全球财经」与「会计准则与税法」→ 生成 news.json

设计原则：
1. 多源冗余，任一源失败不影响其它源
2. 抓取失败时保留上一次的成果，绝不写出空文件
3. 纯标准库，无第三方依赖，可直接放进 GitHub Actions
"""
import json, os, re, sys, time, hashlib, urllib.request
from urllib.parse import urljoin

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept-Language': 'zh-CN,zh;q=0.9'}
TIMEOUT = 20
MAX_PER_SRC = 8


def fetch(url):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT).read()
        for enc in ('utf-8', 'gb18030', 'gbk'):
            try:
                return raw.decode(enc), None
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', 'ignore'), None
    except Exception as e:
        return '', '%s' % type(e).__name__


def clean(t):
    t = re.sub(r'<[^>]+>', '', t or '')
    t = (t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
          .replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'")
          .replace('\u3000', ' ').replace('&ldquo;', '“').replace('&rdquo;', '”'))
    return re.sub(r'\s+', ' ', t).strip()


#   cat,      标签,      列表页,                                                    详情页 URL 正则
SOURCES = [
    # ---------- finance · 全球财经 ----------
    ('finance', '中国人民银行', 'http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html',
     r'/goutongjiaoliu/113456/113469/\d+/index\.(?:html|htm)'),
    ('finance', '财政部', 'http://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/',
     r'\d{6}/t\d+_\d+\.htm'),
    ('finance', '财政部-政策发布', 'http://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/',
     r'\d{6}/t\d+_\d+\.htm'),
    ('finance', '国家统计局', 'https://www.stats.gov.cn/sj/zxfb/',
     r'\d{6}/t\d+_\d+\.html'),
    ('finance', '外汇管理局', 'https://www.safe.gov.cn/safe/zcfg/index.html',
     r'/safe/\d{4}/\d{4}/\d+\.html'),
    # ---------- tax · 会计准则与税法 ----------
    ('tax', '国家税务总局', 'https://www.chinatax.gov.cn/chinatax/n810341/n810755/index.html',
     r'/chinatax/n\d+/n\d+/c\d+/content\.html'),
    ('tax', '财政部会计司', 'http://kjs.mof.gov.cn/zhengcefabu/',
     r'\d{6}/t\d+_\d+\.htm'),
    # 会计司对境外 IP 拒访（GitHub runner 会 FAIL），用中注协作境外兜底
    ('tax', '中国注册会计师协会', 'https://www.cicpa.org.cn/',
     r'\d{6}/t\d+_\d+\.html'),
]


def parse_page(cat, label, list_url, pat):
    txt, err = fetch(list_url)
    if err:
        return [], 'FAIL(%s)' % err
    items, seen = [], set()
    # 统一从 <a href="...">标题</a> / <a ... title="标题"> 提取
    pairs = re.findall(r'<a\b[^>]*?href="([^"#]+)"[^>]*?>(.*?)</a>', txt, re.S)
    titles_attr = dict(re.findall(r'<a\b[^>]*?href="([^"#]+)"[^>]*?title="([^"]{6,120})"', txt))
    for href, inner in pairs:
        href = href.strip()
        if href.startswith('javascript:') or href.startswith('mailto:'):
            continue
        if pat and not re.search(pat, href):
            continue
        full = urljoin(list_url, href)
        if not full.startswith('http'):
            continue
        t = clean(inner) or clean(titles_attr.get(href, ''))
        # 尾部形如 [06-25] 的日期，摘出来当发布日
        dm = re.search(r'\[(\d{2})-(\d{2})\]\s*$', t)
        date_tag = ''
        if dm:
            date_tag = dm.group(1) + '-' + dm.group(2)
            t = t[:dm.start()].strip()
        # 剔除正文中夹的温度([图]、[视频])等标记
        t = re.sub(r'\[(?:图|视频|组图|独家|直播|评论|专题)\]\s*$', '', t).strip()
        if len(t) < 8:
            continue
        if re.match(r'^[\d\-./:：\s年月日]+$', t):       # 纯日期
            continue
        if re.search(r'^(上一页|下一页|首页|尾页|更多|返回|查看全部|跳转到)', t):
            continue
        key = hashlib.md5((t + full).encode('utf-8')).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        items.append({'t': t[:70], 'u': full, 's': label, 'd': date_tag})
        if len(items) >= MAX_PER_SRC:
            break
    return items, 'OK %d 条' % len(items)


def collect():
    data, report = {'finance': [], 'tax': []}, []
    for src in SOURCES:
        cat, label, list_url, pat = src[0], src[1], src[2], src[3]
        try:
            items, msg = parse_page(cat, label, list_url, pat)
        except Exception as e:
            items, msg = [], 'ERR(%s)' % type(e).__name__
        data[cat].extend(items)
        report.append('%-16s %s' % (label, msg))
    for k in data:
        seen, uniq = set(), []
        for x in data[k]:
            key = hashlib.md5(x['t'].encode('utf-8')).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(x)
        data[k] = uniq[:16]
    return data, report


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else 'news.json'
    data, report = collect()
    total = len(data['finance']) + len(data['tax'])

    prev = None
    if os.path.exists(out_path):
        try:
            prev = json.load(open(out_path, encoding='utf-8'))
        except Exception:
            prev = None

    print('== 抓取报告 ==')
    for r in report:
        print('  ' + r)

    if total == 0:
        print('!! 本次抓取为空 → 保留旧文件')
        if prev:
            prev['_stale'] = True
            json.dump(prev, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        sys.exit(0 if prev else 1)

    payload = {
        # 固定输出北京时间，避免 GitHub Actions runner(UTC) 造成时差
        'updated': time.strftime('%Y-%m-%d %H:%M', time.gmtime(time.time() + 8 * 3600)),
        'finance': data['finance'],
        'tax': data['tax'],
        '_report': report,
    }
    json.dump(payload, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('写入 %s：finance %d 条 / tax %d 条' % (out_path, len(data['finance']), len(data['tax'])))


if __name__ == '__main__':
    main()
