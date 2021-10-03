import requests
import sys
import json
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from secret import *

# get app_access_token and tenant_access_token
resp = requests.post('https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal', json={
    'app_id': app_id,
    'app_secret': app_secret
}).json()

app_access_token = resp['app_access_token']
tenant_access_token = resp['tenant_access_token']
user_access_token = ''

# utility


def get(url, access_token):
    resp = requests.get(url, headers={
        'Authorization': f'Bearer {access_token}'
    })
    json = resp.json()
    if json['code'] != 0:
        print(f'Request to {url} failed with: {json}')
        sys.exit(1)
    return json['data']


state = 'backup'
redirect_uri = quote('http://127.0.0.1:8888/backup')
url = f'https://open.feishu.cn/open-apis/authen/v1/index?redirect_uri={redirect_uri}&app_id={app_id}&state={state}'
print(f'Please open {url} in browser')

def print_text_run(data):
    text_run = data['textRun']
    return text_run['text']

def print_paragraph(data):
    paragraph = data['paragraph']
    text = ''
    for element in paragraph['elements']:
        text += walk(element)
    if 'style' in paragraph:
        style = paragraph['style']
        if 'headingLevel' in style:
            # first heading is title
            heading_level = style['headingLevel'] + 1
            text = f'{"#" * heading_level} {text}'
        if 'list' in style:
            l = style['list']
            if l['type'] == 'checkBox':
                text = f'- [ ] {text}'
            elif l['type'] == 'checkedBox':
                text = f'- [x] {text}'
            elif l['type'] == 'number':
                text = f'{l["number"]}. {text}'
            elif l['type'] == 'bullet':
                text = f'- {text}'
    return text

def walk(data):
    if data['type'] == 'paragraph':
        return print_paragraph(data)
    elif data['type'] == 'textRun':
        return print_text_run(data)
    else:
        print(f'Unhandled data type {data["type"]}')
        return ''

def save_doc(path, content):
    content = json.loads(content)
    title = content['title']['elements']
    text = ''
    for element in title:
        text += f'# {walk(element)}'
    text += '\n'
    blocks = content['body']['blocks']
    for block in blocks:
        print(block)
        text += walk(block)
        text += '\n'
    with open(f'{backup_path}{path}', 'w') as f:
        f.write(text)

def list_folder(path, token):
    children = get(
        f'https://open.feishu.cn/open-apis/drive/explorer/v2/folder/{token}/children', user_access_token)

    for token in children['children']:
        data = children['children'][token]
        if data['type'] == 'folder':
            list_folder(f'{path}/{data["name"]}', token)
        else:
            abs_path = f'{path}/{data["name"]}.md'
            print(f'Downloading {abs_path}')
            file = get(
                f'https://open.feishu.cn/open-apis/doc/v2/{data["token"]}/content', user_access_token)
            save_doc(abs_path, file['content'])


class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write("Done!".encode('utf-8'))

        code = parse_qs(urlparse(
            self.path).query).get('code', None)
        if code is None:
            return

        code = code[0]
        resp = requests.post('https://open.feishu.cn/open-apis/authen/v1/access_token', headers={
            'Authorization': f'Bearer {app_access_token}'
        }, json={
            'grant_type': 'authorization_code',
            'code': code
        }).json()

        global user_access_token
        user_access_token = resp['data']['access_token']

        root_folder = get(
            'https://open.feishu.cn/open-apis/drive/explorer/v2/root_folder/meta', user_access_token)
        folder_token = root_folder["token"]
        print(f'Root folder token: {folder_token}, id: {root_folder["id"]}')

        list_folder('', folder_token)


server_address = ('', 8888)
httpd = HTTPServer(server_address, Server)
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    pass
httpd.server_close()

code = input()
