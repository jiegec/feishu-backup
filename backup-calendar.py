from threading import Thread
from typing import List
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import sys
import json
import os
import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from secret import *

# docs: https://open.feishu.cn/document/server-docs/calendar-v4/overview

app_access_token = ""
tenant_access_token = ""
user_access_token = ""
filter = None


def init():
    # get app_access_token and tenant_access_token
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    ).json()

    global app_access_token
    app_access_token = resp["app_access_token"]

    global tenant_access_token
    tenant_access_token = resp["tenant_access_token"]

    print("Tenant Access Token:", tenant_access_token)
    print("App Access Token:", app_access_token)


# utility


def get(url, access_token):
    # retry logic from https://gist.github.com/benjiao/28dc36bd87121b3273e0b3e079a8e8d8
    retries = Retry()
    with requests.Session() as s:
        s.mount("http://", HTTPAdapter(max_retries=retries))
        s.mount("https://", HTTPAdapter(max_retries=retries))

        resp = s.get(url, headers={"Authorization": f"Bearer {access_token}"})
        json = resp.json()
        if json["code"] != 0:
            print(f"Request to {url} failed with: {json}")
            sys.exit(1)
        return json["data"]


def parse_time(data):
    if "timestamp" in data:
        time = datetime.fromtimestamp(
            int(data["timestamp"]), ZoneInfo(data["timezone"])
        ).strftime("%Y%m%dT%H%M%S")
        return f"TZID={data['timezone']}:{time}"
    else:
        date = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%Y%m%d")
        return f"VALUE=DATE:{date}"


state = "backup"
redirect_uri = quote("http://127.0.0.1:8888/backup")
url = f"https://open.feishu.cn/open-apis/authen/v1/index?redirect_uri={redirect_uri}&app_id={app_id}&state={state}"
print(f"Please open {url} in browser")


def work(code):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/authen/v1/access_token",
        headers={"Authorization": f"Bearer {app_access_token}"},
        json={"grant_type": "authorization_code", "code": code},
    ).json()

    global user_access_token
    user_access_token = resp["data"]["access_token"]

    folder = f"{backup_path}/calendar"
    os.makedirs(folder, exist_ok=True)
    print(f"Output files are written to {folder}")

    # list calendars
    calendars = get(
        "https://open.feishu.cn/open-apis/calendar/v4/calendars?page_size=500",
        user_access_token,
    )
    calendars = calendars["calendar_list"]
    print(f"Found {len(calendars)} calendars")

    for calendar in calendars:
        calendar_id = calendar["calendar_id"]
        print(f"Handling calendar {calendar['summary']} {calendar_id}")

        page_token = None
        while True:
            if page_token is not None:
                events_url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events?page_token={page_token}&anchor_time=0"
            else:
                events_url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events?anchor_time=0"

            data = get(
                events_url,
                user_access_token,
            )
            events = data["items"]
            print(f"Found {len(events)} events")

            for event in events:
                # skip cancelled events
                if event["status"] == "cancelled":
                    continue

                event_id = event["event_id"]
                # save raw json
                with open(
                    f"{backup_path}/calendar/{event_id}.json", "w", encoding="utf-8"
                ) as file:
                    print(json.dumps(event), file=file)

                # save icalendar
                with open(
                    f"{backup_path}/calendar/{event_id}.ics", "w", encoding="utf-8"
                ) as file:
                    create_time = datetime.fromtimestamp(
                        int(event["create_time"]), timezone.utc
                    ).strftime("%Y%m%dT%H%M%SZ")
                    start_time = parse_time(event["start_time"])
                    end_time = parse_time(event["end_time"])
                    print(
                        f"""BEGIN:VCALENDAR
PRODID:-//Jiajie Chen///feishu-backup v1.0//EN
VERSION:2.0
BEGIN:VEVENT
CREATED:{create_time}
DTSTAMP:{create_time}
UID:{event['event_id']}
ORGANIZER;CN={event['event_organizer']['display_name']}
DTSTART;{start_time}
DTEND;{end_time}
SUMMARY:{event['summary']}
END:VEVENT
END:VCALENDAR""",
                        file=file,
                    )

            if data["has_more"]:
                page_token = data["page_token"]
            else:
                break
    print("Finished!")


class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write("Done!".encode("utf-8"))

        code = parse_qs(urlparse(self.path).query).get("code", None)
        if code is None:
            return

        code = code[0]
        thread = Thread(target=work, args=(code,))
        thread.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup feishu calendar events")

    args = parser.parse_args()

    init()
    server_address = ("", 8888)
    httpd = HTTPServer(server_address, Server)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
