"""
HES-SO PaperCut Print Client - Fast HTTP Engine for Stats
"""

import ssl
import re
import urllib.request
import urllib.parse
import http.cookiejar
import html as html_mod

class PaperCutSession:
    def __init__(self, host, username, password):
        self.host = host
        self.username = username
        self.password = password
        self.cj = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ctx)
        )
        self.is_logged_in = False

    def request(self, method, url, data=None, headers=None, follow=True):
        req_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        if headers:
            req_headers.update(headers)
        body = data.encode("utf-8") if isinstance(data, str) else data
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            res = self.opener.open(req, timeout=12)
            return res.status, res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            raise e

    def login(self):
        url_init = f"https://{self.host}/user"
        status, body = self.request("GET", url_init)
        m = re.search(r'<form[^>]*action="([^"]*)"', body)
        if not m:
            raise Exception("Could not parse login form action from portal.")
        formaction = m.group(1)

        params = urllib.parse.urlencode({
            "service": "direct/1/Home/$Form",
            "sp": "S0",
            "Form0": "$Hidden$0,$Hidden$1,$Hidden$2,inputUsername,inputPassword,$Submit$1,$PropertySelection",
            "$Hidden$0": "F",
            "$Hidden$1": "X",
            "$Hidden$2": "X",
            "inputUsername": self.username,
            "inputPassword": self.password,
            "$Submit$1": "Log in",
            "$PropertySelection": "en",
        })
        url_login = f"https://{self.host}{formaction}"
        status, body = self.request("POST", url_login, data=params, headers={
            "Origin": f"https://{self.host}",
            "Content-Type": "application/x-www-form-urlencoded"
        })
        if "Invalid username or password" in body:
            raise Exception("Invalid username or password.")
        self.is_logged_in = True

    def get_stats(self):
        if not self.is_logged_in:
            self.login()
        status, html = self.request("GET", f"https://{self.host}/app?service=page/UserSummary")
        stats = {}

        for key, cls in [("balance", "stat-bal"), ("jobs", "stat-jobs"), ("pages", "stat-pages")]:
            m = re.search(r'<div class="widget ' + cls + r'"[^>]*>(.*?)</div>\s*</div>', html, re.S)
            if m:
                txt = re.sub(r'<[^>]+>', ' ', m.group(1))
                val_m = re.search(r'([\d.,]+\s*(?:CHF|pages|jobs)?)', txt, re.I)
                stats[key] = val_m.group(1).strip() if val_m else "?"
            else:
                stats[key] = "?"

        env_m = re.search(r'<ul id="enviroTable"[^>]*>(.*?)</ul>', html, re.S)
        if env_m:
            env_txt = env_m.group(1)
            t_m = re.search(r'([\d.,]+%\s*of\s*a\s*tree)', env_txt, re.I)
            c_m = re.search(r'([\d.,]+\s*kg\s*of\s*CO2)', env_txt, re.I)
            stats["trees"] = t_m.group(1).replace("of a tree", "").strip() if t_m else "?"
            stats["co2"] = c_m.group(1).replace("kg of CO2", "kg").strip() if c_m else "?"
        else:
            stats["trees"] = "?"
            stats["co2"] = "?"

        status, logs_html = self.request("GET", f"https://{self.host}/app?service=page/UserPrintLogs")
        recent = []
        logs_html = re.sub(r'<span class="responsive-label">.*?</span>', '', logs_html, flags=re.S)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', logs_html, re.S)
        for r in rows:
            if "usageDateColumnValue" in r:
                date_m = re.search(r'class="usageDateColumnValue".*?<span class="smallText">(.*?)</span>', r, re.S)
                printer_m = re.search(r'class="printerDisplayNameColumnValue".*?<div class="smallText">(.*?)</div>', r, re.S)
                pages_m = re.search(r'class="totalPagesColumnValue".*?<div[^>]*>(.*?)</div>', r, re.S)
                cost_m = re.search(r'class="usageCostColumnValue".*?<div[^>]*>(.*?)</div>', r, re.S)
                doc_m = re.search(r'class="documentNameColumnValue".*?<span class="smallText">(.*?)</span>', r, re.S)
                status_m = re.search(r'class="statusColumnValue".*?<div class="smallText">(.*?)</div>', r, re.S)

                clean = lambda m: re.sub(r'\s+', ' ', html_mod.unescape(re.sub(r'<[^>]+>', '', m.group(1)))).strip() if m else "?"
                recent.append({
                    "date": clean(date_m),
                    "printer": clean(printer_m).replace("vmenpprint1\\", ""),
                    "pages": clean(pages_m),
                    "cost": clean(cost_m),
                    "doc": clean(doc_m),
                    "status": clean(status_m),
                })
        stats["recent_jobs"] = recent

        status, web_html = self.request("GET", f"https://{self.host}/app?service=page/UserWebPrint")
        web_html = re.sub(r'<span class="responsive-label">.*?</span>', '', web_html, flags=re.S)
        queued = []
        q_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', web_html, re.S)
        for r in q_rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)
            if len(cells) >= 6:
                clean_cell = lambda c: re.sub(r'\s+', ' ', html_mod.unescape(re.sub(r'<[^>]+>', '', c))).strip()
                queued.append({
                    "date": clean_cell(cells[1]),
                    "printer": clean_cell(cells[2]).replace("vmenpprint1\\", ""),
                    "doc": clean_cell(cells[3]),
                    "pages": clean_cell(cells[4]),
                    "cost": clean_cell(cells[5]),
                    "status": clean_cell(cells[6]) if len(cells) > 6 else "Pending",
                })
        stats["queued_jobs"] = queued
        return stats