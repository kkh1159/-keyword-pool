import os, time, hmac, base64, hashlib, json, random, threading
from datetime import datetime
import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Keyword Pool")

POOL_FILE = "pool.json"
REFRESH_DAYS = 30

SEEDS = ["제휴마케팅","부업","애드센스","쿠팡파트너스","블로그수익",
         "스레드수익화","어필리에이트","티스토리","챗gpt부업","재택부업"]
MIN_MOBILE, MAX_MOBILE = 100, 50000
MAX_DOC_QUERIES = 300
RATIO_A = 0.20
TOPIC_WORDS = ["부업","수익","제휴","투잡","부수입","재택","무자본","파트너스",
               "애드센스","어필리에이트","수익화","자동화","블로그","티스토리"]
EXCLUDE_WORDS = ["채용","구인","학원","자격증","대출","보험","중고","가격","쿠폰",
                 "할인코드","알바","단기","일당","생동성","손부업","미싱","십자수",
                 "포장","조립","인형","스티커","단체티","티셔츠","대행","꾸미는법","이웃늘리기"]

DEFAULT_POOL = ["쿠팡파트너스하는법","스레드수익화","티스토리블로그수익","CPA제휴마케팅",
    "구글애드센스","구글애드센스승인","구글애드센스블로그","애드센스","블로그애드포스트",
    "네이버블로그수익","블로그로돈벌기","워드프레스수익","블로그방문자늘리기","재택부업",
    "집에서하는부업","집에서할수있는부업","집부업","인터넷부업","구글부업","당근부업",
    "데이터라벨링부업","공무원부업","교사부업","간호사부업","임산부부업","직장인투잡추천"]

_used = set()
_refreshing = False


def load_pool():
    if os.path.exists(POOL_FILE):
        try:
            with open(POOL_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("keywords"):
                return d
        except Exception:
            pass
    return {"updated": "1970-01-01", "keywords": DEFAULT_POOL}


def save_pool(keywords):
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now().strftime("%Y-%m-%d"),
                   "keywords": keywords}, f, ensure_ascii=False)


def days_old(updated):
    try:
        return (datetime.now() - datetime.strptime(updated, "%Y-%m-%d")).days
    except Exception:
        return 9999


def num(v):
    s = str(v).strip()
    if s in ("< 10", "<10", ""):
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def ask_related(keyword):
    uri = "/keywordstool"
    ts = str(round(time.time() * 1000))
    sig = base64.b64encode(hmac.new(
        os.getenv("NAVER_AD_SECRET_KEY", "").encode(),
        f"{ts}.GET.{uri}".encode(), hashlib.sha256).digest()).decode()
    headers = {"X-Timestamp": ts,
               "X-API-KEY": os.getenv("NAVER_AD_ACCESS_LICENSE", ""),
               "X-Customer": str(os.getenv("NAVER_AD_CUSTOMER_ID", "")),
               "X-Signature": sig}
    try:
        r = requests.get("https://api.searchad.naver.com" + uri, headers=headers,
                         params={"hintKeywords": keyword.replace(" ", ""),
                                 "showDetail": "1"}, timeout=20)
        return r.json().get("keywordList", []) if r.status_code == 200 else []
    except Exception:
        return []


def monthly_docs(keyword):
    url = "https://naverapihub.apigw.ntruss.com/search/v1/blog"
    headers = {"X-NCP-APIGW-API-KEY-ID": os.getenv("NAVER_CLIENT_ID", ""),
               "X-NCP-APIGW-API-KEY": os.getenv("NAVER_CLIENT_SECRET", "")}
    try:
        r = requests.get(url, headers=headers,
                         params={"query": keyword, "display": 100, "sort": "date"},
                         timeout=10)
        if r.status_code != 200:
            return None
        dates = []
        for it in r.json().get("items", []):
            d = it.get("postdate", "")
            if len(d) == 8:
                try:
                    dates.append(datetime.strptime(d, "%Y%m%d"))
                except ValueError:
                    pass
        if len(dates) < 2:
            return None
        span = (max(dates) - min(dates)).days or 1
        return int(len(dates) / span * 30)
    except Exception:
        return None


def is_on_topic(k):
    low = k.lower()
    if any(w in low for w in EXCLUDE_WORDS):
        return False
    return any(w in low for w in TOPIC_WORDS)


def rebuild():
    global _refreshing
    if _refreshing:
        return
    _refreshing = True
    try:
        pool = {}
        for seed in SEEDS:
            for it in ask_related(seed):
                kw = it.get("relKeyword", "").strip()
                if not kw or kw in pool:
                    continue
                pc, mo = num(it.get("monthlyPcQcCnt")), num(it.get("monthlyMobileQcCnt"))
                pool[kw] = {"keyword": kw, "mobile": mo, "total": pc + mo}
            time.sleep(0.3)
        cands = [v for v in pool.values()
                 if MIN_MOBILE <= v["mobile"] <= MAX_MOBILE and is_on_topic(v["keyword"])]
        cands.sort(key=lambda x: (-len(x["keyword"]), -x["total"]))
        good = []
        for c in cands[:MAX_DOC_QUERIES]:
            m = monthly_docs(c["keyword"])
            if not m or m >= 3000:
                continue
            ratio = m / c["total"] if c["total"] else 999
            if ratio <= RATIO_A:
                good.append((ratio, c["keyword"]))
            time.sleep(0.12)
        good.sort()
        result = [k for _, k in good[:30]]
        if result:
            save_pool(result)
            _used.clear()
    finally:
        _refreshing = False


class Empty(BaseModel):
    pass


@app.post("/pick")
def pick(body: Empty | None = None):
    data = load_pool()
    if days_old(data["updated"]) >= REFRESH_DAYS and not _refreshing:
        threading.Thread(target=rebuild, daemon=True).start()
    pool = data["keywords"]
    remain = [k for k in pool if k not in _used]
    if not remain:
        _used.clear()
        remain = pool
    picked = random.choice(remain)
    _used.add(picked)
    return {"keyword": picked, "remaining": len(remain) - 1,
            "pool_updated": data["updated"], "pool_size": len(pool),
            "refreshing": _refreshing}


@app.get("/refresh")
def refresh():
    if _refreshing:
        return {"status": "이미 갱신 중입니다"}
    threading.Thread(target=rebuild, daemon=True).start()
    return {"status": "갱신 시작. 2분 뒤 /status 확인"}


@app.get("/status")
def status():
    d = load_pool()
    return {"refreshing": _refreshing, "updated": d["updated"],
            "days_old": days_old(d["updated"]),
            "count": len(d["keywords"]), "keywords": d["keywords"]}


@app.get("/")
def root():
    return {"ok": True}
