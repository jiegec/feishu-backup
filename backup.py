from typing import List
import requests
import sys
import json
import os
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from secret import *

# docs: https://open.feishu.cn/document/ukTMukTMukTM/uczNzUjL3czM14yN3MTN

# get app_access_token and tenant_access_token
resp = requests.post('https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal', json={
    'app_id': app_id,
    'app_secret': app_secret
}).json()

app_access_token = resp['app_access_token']
tenant_access_token = resp['tenant_access_token']
user_access_token = ''

print('Tenant Access Token:', tenant_access_token)
print('App Access Token:', app_access_token)

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

# doc spec
# https://open.feishu.cn/document/ukTMukTMukTM/uAzM5YjLwMTO24CMzkjN


def render_markdown_table(data: List[List[str]]) -> str:
    text = ''
    for i, row in enumerate(data):
        text += '|'
        for col in row:
            text += ' '
            if isinstance(col, list):
                # text run
                text += ''.join(map(lambda v: v['text'], col))
            else:
                # string/number
                text += str(col)
            text += ' |'
        text += '\n'

        # separator
        if i == 0:
            text += '|'
            text += '-|' * len(row)
            text += '\n'
    return text


class Dumper:
    def __init__(self) -> None:
        self.image_tokens = []

    def print_text_run(self, data) -> str:
        text_run = data['textRun']
        return text_run['text']

    def print_paragraph(self, data) -> str:
        paragraph = data['paragraph']
        text = ''
        for element in paragraph['elements']:
            text += self.walk(element)
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

    def print_gallery(self, data) -> str:
        images = data['gallery']['imageList']
        text = ''
        for image in images:
            token = image['fileToken']
            file_name = f'{token}.png'
            self.image_tokens.append(token)
            text += f'![]({file_name})'
        return text

    def print_table(self, data) -> str:
        rows = data['table']['tableRows']
        text = ''
        table_data = []
        for row in rows:
            cells = row['tableCells']
            row_data = []
            for cell in cells:
                body = cell['body']
                blocks = body['blocks']
                cell_content = ''
                if blocks != None:
                    for block in blocks:
                        cell_content += self.walk(block)

                row_data.append(cell_content)
            table_data.append(row_data)

        # print table
        return render_markdown_table(table_data)

    def print_sheet(self, data) -> str:
        sheet_token = data['sheet']['token']
        # first part is token
        token = sheet_token.split('_')[0]
        # second part is sheet id
        sheet_id = sheet_token.split('_')[1]
        content = get(
            f'https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/values/{sheet_id}?dateTimeRenderOption=FormattedString', user_access_token)
        values = content['valueRange']['values']
        print(values)
        return render_markdown_table(values)

    def walk(self, data):
        if data['type'] == 'paragraph':
            return self.print_paragraph(data)
        elif data['type'] == 'textRun':
            return self.print_text_run(data)
        elif data['type'] == 'gallery':
            return self.print_gallery(data)
        elif data['type'] == 'table':
            return self.print_table(data)
        elif data['type'] == 'sheet':
            return self.print_sheet(data)
        else:
            print(f'Unhandled data type {data["type"]}')
            print(data)
            return ''


def save_doc(path, file_name, content):
    dumper = Dumper()
    content = json.loads(content)
    title = content['title']['elements']
    text = ''
    for element in title:
        text += f'# {dumper.walk(element)}'
    text += '\n'
    blocks = content['body']['blocks']
    for block in blocks:
        text += dumper.walk(block)
        text += '\n'
    os.makedirs(f'{backup_path}{path}', exist_ok=True)
    with open(f'{backup_path}{path}/{file_name}', 'w') as f:
        f.write(text)

    for token in dumper.image_tokens:
        file_name = f'{token}.png'
        file_path = f'{backup_path}{path}/{file_name}'
        if os.path.exists(file_path):
            continue
        with open(f'{backup_path}{path}/{file_name}', "wb") as file:
            url = f'https://open.feishu.cn/open-apis/drive/v1/medias/{token}/download'
            print(f'Downloading image {token}')
            resp = requests.get(url, headers={
                'Authorization': f'Bearer {user_access_token}'
            })
            file.write(resp.content)


def save_sheet(path, file_name, token):
    metainfo = get(
        f'https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/metainfo', user_access_token)
    sheets = metainfo['sheets']
    text = ''
    for sheet in sheets:
        sheet_id = sheet['sheetId']

        text += f'# {sheet["title"]}\n'
        content = get(
            f'https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/values/{sheet_id}?dateTimeRenderOption=FormattedString', user_access_token)
        values = content['valueRange']['values']
        text += render_markdown_table(values)

    os.makedirs(f'{backup_path}{path}', exist_ok=True)
    with open(f'{backup_path}{path}/{file_name}', 'w') as f:
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
            if data['type'] == 'doc':
                file = get(
                    f'https://open.feishu.cn/open-apis/doc/v2/{data["token"]}/content', user_access_token)
                save_doc(path, f'{data["name"]}.md', file['content'])
            elif data['type'] == 'sheet':
                save_sheet(path, f'{data["name"]}.md', data['token'])
            else:
                print(f'Unsupported type: {data["type"]}')


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

        # list documents
        root_folder = get(
            'https://open.feishu.cn/open-apis/drive/explorer/v2/root_folder/meta', user_access_token)
        folder_token = root_folder["token"]
        # print(f'Found Root folder token: {folder_token}, id: {root_folder["id"]}')

        list_folder('', folder_token)

        # list wikis
        # TODO: paging
        wikis = get(
            'https://open.feishu.cn/open-apis/wiki/v2/spaces?page_size=10', user_access_token)
        for item in wikis['items']:
            space_name = item['name']
            print(f'Found wiki space {space_name}')
            space_id = item['space_id']

            # get nodes
            nodes = get(
                f'https://open.feishu.cn/open-apis/wiki/v2/spaces/{space_id}/nodes?page_size=10', user_access_token)
            for item in nodes['items']:
                if item['obj_type'] == 'doc':
                    path = f'/知识库/{space_name}'
                    abs_path = f'{path}/{item["title"]}.md'
                    print(f'Downloading {abs_path}')
                    file = get(
                        f'https://open.feishu.cn/open-apis/doc/v2/{item["obj_token"]}/content', user_access_token)
                    save_doc(path, f'{item["title"]}.md', file['content'])


server_address = ('', 8888)
httpd = HTTPServer(server_address, Server)
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    pass
httpd.server_close()

code = input()
