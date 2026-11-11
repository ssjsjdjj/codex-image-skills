"""Read a product row from a Feishu Bitable view through the official Open API."""

import csv
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image

API = "https://open.feishu.cn/open-apis"
PAGE_SIZE = 100
JSON_LIMIT = 8 * 1024 * 1024
IMAGE_LIMIT = 40 * 1024 * 1024
INFO_FIELDS = {
    "名称": ("商品名称", "产品名称", "商品名", "产品名", "款式名称", "款名", "品名", "名称"),
    "货号": ("货号", "款号", "商品款号", "产品货号", "产品款号"),
    "尺码": ("尺码范围", "商品尺码", "产品尺码", "尺码段", "规格尺码", "尺码"),
    "材质": ("材质", "面料成分", "纤维成分", "成分", "面料", "面料信息", "商品材质"),
}
COLOR_FIELDS = ("颜色", "颜色名称", "色名", "配色", "商品颜色", "产品颜色")
TABLE_FIELDS = {
    "size_table": ("尺码表", "选尺码", "03选尺码", "尺寸表", "尺码表数据", "size_table"),
    "quick_size": ("尺码快选", "尺码推荐", "05尺码快选", "推荐尺码", "推荐尺码表", "尺码快选数据", "quick_size"),
    "try_on": ("试穿报告", "试穿表", "试穿数据", "模特试穿", "try_on"),
}
STRUCTURED_FIELDS = ("product_data", "商品资料 JSON", "套版资料 JSON", "商品资料", "详情页数据", "套版数据")
PRODUCT_IMAGES = ("透明图", "透明商品图", "透明产品图", "商品透明图", "产品透明图", "商品图", "产品图", "SKC", "SKC图", "SKC图片")
SCENE_IMAGES = ("模特图", "模特图片", "场景图", "场景图片", "模特照片", "场景照片")


class FeishuImportError(ValueError):
    pass


class _ExpiredConnection(FeishuImportError):
    pass


@dataclass
class ImportedRow:
    data: dict
    source: str
    record_id: str
    attachments: list[dict]
    products: dict[str, Path]
    scenes: list[Path | None]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = build_opener(NoRedirect)


def parse_base_link(value):
    value = str(value).strip()
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (parts.scheme != "https" or not (host == "feishu.cn" or host.endswith(".feishu.cn"))
                or parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise FeishuImportError("请填写以 https:// 开头的飞书多维表格视图链接。") from None
    match = re.fullmatch(r"/(base|wiki)/([A-Za-z0-9_-]{1,100})/?", parts.path)
    if not match:
        raise FeishuImportError("请在飞书打开目标数据表，复制带 /base/ 或 /wiki/ 的视图链接。")
    query = parse_qs(parts.query)
    tables, views = query.get("table", []), query.get("view", [])
    if (len(tables) > 1 or len(views) > 1 or tables and not re.fullmatch(r"tbl[A-Za-z0-9]+", tables[0])
            or views and not re.fullmatch(r"vew[A-Za-z0-9]+", views[0])):
        raise FeishuImportError("链接中的数据表或视图标识格式异常，请重新复制飞书地址栏链接。")
    kind, token = match.groups()
    table, view = tables[0] if tables else "", views[0] if views else ""
    clean = urlunsplit(("https", host, f"/{kind}/{token}", urlencode({key: item for key, item in
                        (("table", table), ("view", view)) if item}), ""))
    return kind, token, table, view, clean


def parse_link(value):
    result = parse_base_link(value)
    if not result[2] or not result[3]:
        raise FeishuImportError("链接需要同时包含 table 和 view。请进入飞书的目标表格视图后复制地址栏链接。")
    return result


def request_bytes(url, *, token=None, body=None, limit=JSON_LIMIT, content_type="application/json; charset=utf-8"):
    headers = {"User-Agent": "DetailWorkbench/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=headers)
    try:
        with OPENER.open(request, timeout=18) as response:
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > limit:
                raise FeishuImportError("飞书返回的文件超过本次导入的大小限制。")
            data = response.read(limit + 1)
    except HTTPError as error:
        if error.code in (401, 403):
            raise FeishuImportError("飞书凭证无效、已过期或没有该表及附件的读取权限。") from None
        if error.code == 429:
            raise FeishuImportError("飞书请求较频繁，请稍后重试。") from None
        raise FeishuImportError(f"飞书接口返回 HTTP {error.code}。请检查链接和连接设置。") from None
    except FeishuImportError:
        raise
    except (URLError, OSError, ValueError):
        raise FeishuImportError("无法连接飞书开放平台，请检查网络后重试。") from None
    if len(data) > limit:
        raise FeishuImportError("飞书返回的文件超过本次导入的大小限制。")
    return data


def json_response(payload):
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError):
        raise FeishuImportError("飞书接口没有返回可读取的 JSON 数据。") from None
    if not isinstance(data, dict):
        raise FeishuImportError("飞书接口响应格式异常。")
    return data


def request_data(endpoint, token, body=None, query=None):
    url = API + endpoint + ("?" + urlencode(query) if query else "")
    raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    payload = json_response(request_bytes(url, token=token, body=raw))
    code = payload.get("code")
    if code in {99991661, 99991663, 99991668, 99991677, 20006, 20013}:
        raise _ExpiredConnection(f"飞书连接已失效（{code}），请重新连接飞书。")
    if code in {99991672, 99991676, 99991679}:
        raise FeishuImportError(f"当前飞书连接缺少读取权限（{code}）。请让管理员为应用开通多维表格读取权限，并确认表格已授权。")
    if code == 1254302:
        raise FeishuImportError("该表开启了高级权限，当前连接无法读取。请让管理员在表格的权限设置中授权当前用户或应用。")
    if code != 0:
        hint = f"（{code}）" if isinstance(code, int) else ""
        raise FeishuImportError(f"飞书读取失败{hint}。请核对表格视图、凭证权限及文档共享设置。")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise FeishuImportError("飞书接口响应缺少记录数据。")
    return data


def connection_token(value):
    token = (value or "").strip()
    if token:
        if not re.fullmatch(r"[A-Za-z0-9._~+/=\-]{1,8192}", token):
            raise FeishuImportError("飞书访问凭证格式异常，请粘贴令牌本身。")
        return token
    from feishu_auth import ConfigurationRequired, get_access_token

    try:
        return get_access_token()
    except ConfigurationRequired:
        token = os.environ.get("FEISHU_ACCESS_TOKEN", "").strip()
        if not token:
            raise
        if not re.fullmatch(r"[A-Za-z0-9._~+/=\-]{1,8192}", token):
            raise FeishuImportError("飞书访问凭证格式异常，请检查环境变量中的凭证。")
        return token


def select_record(kind, app, table, view, row, token):
    if kind == "wiki":
        result = request_data("/wiki/v2/spaces/get_node", token, query={"token": app})
        node = result.get("node") or {}
        app = node.get("obj_token")
        if node.get("obj_type") != "bitable" or not isinstance(app, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", app):
            raise FeishuImportError("该知识库链接对应的文档类型不是多维表格。")
    endpoint = f"/bitable/v1/apps/{app}/tables/{table}/records/search"
    remaining = row
    page_size = min(PAGE_SIZE, row)
    cursor = None
    seen_cursors = set()
    while remaining > 0:
        query = {"page_size": page_size}
        if cursor:
            query["page_token"] = cursor
        result = request_data(endpoint, token, body={"view_id": view}, query=query)
        items = result.get("items") or []
        if not isinstance(items, list):
            raise FeishuImportError("飞书返回的记录格式异常。")
        if remaining <= len(items):
            record = items[remaining - 1]
            if isinstance(record, dict) and isinstance(record.get("fields"), dict) and record.get("record_id"):
                return record
            raise FeishuImportError("该行缺少记录 ID 或字段，请检查飞书视图。")
        remaining -= len(items)
        if not result.get("has_more"):
            raise FeishuImportError(f"此视图中，当前凭证可读取的记录没有第 {row} 行。")
        cursor = result.get("page_token")
        if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
            raise FeishuImportError("飞书分页未完成。请检查视图状态并重新读取。")
        seen_cursors.add(cursor)


def field_key(value):
    return re.sub(r"[\s\u200b:：]+", "", str(value)).casefold()


def find_field(fields, names):
    for name in names:
        key = field_key(name)
        if key in fields and fields[key] not in (None, "", [], {}):
            return fields[key]
    return None


def text_value(value):
    if isinstance(value, str):
        return value.strip(" \r\n")
    if type(value) in (int, float):
        return str(value)
    if isinstance(value, list):
        if all(isinstance(item, dict) and isinstance(item.get("text"), str) for item in value):
            return "".join(item["text"] for item in value).strip(" \r\n")
        return " / ".join(filter(None, map(text_value, value)))
    if isinstance(value, dict) and "file_token" not in value:
        for key in ("text", "value", "name", "label"):
            if key in value:
                return text_value(value[key])
    return ""


def color_values(value):
    text = text_value(value)
    return list(dict.fromkeys(color.strip() for color in re.split(r"[/／、,，;；\r\n]+", text) if color.strip()))


def structured_value(value):
    if isinstance(value, (dict, list)) and not text_value(value):
        return value
    text = text_value(value)
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def table_value(value, kind):
    content = value if isinstance(value, list) and all(isinstance(row, list) for row in value) else structured_value(value)
    if isinstance(content, dict):
        return content
    if isinstance(content, list) and len(content) >= 2 and all(isinstance(row, list) for row in content):
        matrix = content
    else:
        raw = text_value(value)
        if "\n" not in raw or not ("\t" in raw or "," in raw):
            return None
        matrix = list(csv.reader(io.StringIO(raw), delimiter="\t" if "\t" in raw else ","))
    if not matrix or len(matrix) < 2 or len(matrix[0]) < 2 or any(len(row) != len(matrix[0]) for row in matrix):
        return None
    headers, rows = matrix[0], matrix[1:]
    if kind == "quick_size":
        return {"columns": headers[1:], "rows": [row[0] for row in rows], "data": [row[1:] for row in rows]}
    return {"headers": headers, "rows": rows}


def extract_attachments(fields):
    return [(name, item) for name, value in fields.items() if isinstance(value, list)
            for item in value if isinstance(item, dict) and isinstance(item.get("file_token"), str)]


def attachment_endpoint(item):
    file_token = item["file_token"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", file_token):
        raise FeishuImportError("飞书附件标识格式异常。")
    base = f"{API}/drive/v1/medias/{file_token}/download"
    # The official response may include advanced attachment-permission parameters.
    url = item.get("url")
    if isinstance(url, str) and (url == base or url.startswith(base + "?")):
        params = parse_qs(urlsplit(url).query)
        if params.get("extra"):
            return base + "?" + urlencode({"extra": params["extra"][0]})
    return base


def image_assignments(items, colors, token, cache_dir, warnings):
    if cache_dir is None:
        return {}, []
    products, scenes = {}, [None] * 4
    folder = None
    matched = {color: [] for color in colors}
    scene_slots = [[] for _ in scenes]
    product_keys = {field_key(value) for value in PRODUCT_IMAGES}
    scene_keys = {field_key(value) for value in SCENE_IMAGES}
    for field, item in items:
        key = field_key(field)
        name = str(item.get("name", ""))
        if Path(name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        candidates = [color for color in colors if color in name or color in field]
        if len(candidates) == 1 and (key in product_keys or any(key.startswith(prefix) for prefix in product_keys)):
            matched[candidates[0]].append(item)
            continue
        numbered = re.fullmatch(r"(.+?)[_-]?([1-4])", key)
        if numbered and numbered[1] in scene_keys:
            scene_slots[int(numbered[2]) - 1].append(item)
    for name in SCENE_IMAGES:
        group = [item for field, item in items if field_key(field) == field_key(name)
                 and Path(str(item.get("name", ""))).suffix.lower() in {".jpg", ".jpeg", ".png"}]
        for index, item in enumerate(group[:4]):
            scene_slots[index].append(item)

    def bind(candidates, label, transparent):
        nonlocal folder
        if len(candidates) != 1:
            if candidates:
                warnings.append(f"飞书附件有多个候选 · {label}，请在图片匹配里确认。")
            return None
        try:
            raw = request_bytes(attachment_endpoint(candidates[0]), token=token, limit=IMAGE_LIMIT)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1:
                    raise FeishuImportError("附件不是静态 PNG 或 JPG。")
                if transparent:
                    if image.format != "PNG" or ("A" not in image.getbands() and "transparency" not in image.info):
                        raise FeishuImportError("商品图附件缺少透明通道。")
                    if image.width * image.height > 50_000_000 or min(image.size) < 32:
                        raise FeishuImportError("商品图尺寸超出套版支持范围。")
                    low, high = image.convert("RGBA").getchannel("A").getextrema()
                    if low == 255 or high == 0:
                        raise FeishuImportError("商品图附件需要包含商品和透明背景。")
                suffix = ".png" if image.format == "PNG" else ".jpg"
            if folder is None:
                Path(cache_dir).mkdir(parents=True, exist_ok=True)
                folder = Path(mkdtemp(prefix="飞书素材-", dir=cache_dir))
            target = folder / f"{'product' if transparent else 'scene'}-{len(list(folder.iterdir())) + 1}{suffix}"
            target.write_bytes(raw)
            return target
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            description = str(error) if isinstance(error, FeishuImportError) else "附件内容无法作为图片读取。"
            warnings.append(f"{label} · {description}")
            return None

    for color, candidates in matched.items():
        path = bind(candidates, f"{color}商品图", True)
        if path:
            products[color] = path
    for index, candidates in enumerate(scene_slots):
        scenes[index] = bind(candidates, f"模特图 {index + 1}", False)
    while scenes and scenes[-1] is None:
        scenes.pop()
    return products, scenes


def import_row(url, row, *, access_token=None, cache_dir=None):
    kind, app, table, view, clean = parse_link(url)
    row_text = str(row).strip()
    if not re.fullmatch(r"[0-9]{1,5}", row_text) or not 1 <= int(row_text) <= 20000:
        raise FeishuImportError("行号请填 1–20000 的整数，从视图第一条数据开始数。")
    row = int(row_text)
    token = connection_token(access_token)
    try:
        record = select_record(kind, app, table, view, row, token)
    except _ExpiredConnection as error:
        if access_token and access_token.strip():
            raise
        from feishu_auth import ConfigurationRequired, get_access_token

        try:
            token = get_access_token(force_refresh=True)
        except ConfigurationRequired:
            raise error from None
        record = select_record(kind, app, table, view, row, token)
    return product_from_record(record, token, clean, label=f"飞书第 {row} 行", cache_dir=cache_dir)


def product_from_record(record, token, clean, *, label="飞书记录", cache_dir=None):
    fields = {field_key(name): value for name, value in record["fields"].items()}
    attachments = extract_attachments(record["fields"])
    warnings = []
    payload = structured_value(find_field(fields, STRUCTURED_FIELDS))
    if not isinstance(payload, dict):
        payload = {}
    if not payload:
        json_items = [item for field, item in attachments if Path(str(item.get("name", ""))).name.casefold() == "product_data.json"
                      or (field_key(field) in {field_key(name) for name in STRUCTURED_FIELDS}
                          and Path(str(item.get("name", ""))).suffix.lower() == ".json")]
        if len(json_items) == 1:
            try:
                payload = json_response(request_bytes(attachment_endpoint(json_items[0]), token=token))
            except FeishuImportError as error:
                warnings.append(f"商品资料 JSON 附件未读入 · {error}")
        elif json_items:
            warnings.append("商品资料 JSON 附件有多份，请手动选择经确认的一份。")
    info = payload.get("info")
    if not isinstance(info, dict):
        info = {}
    values = {key: text_value(find_field(fields, aliases)) for key, aliases in INFO_FIELDS.items()}
    payload_code = text_value(info.get("货号"))
    if values["货号"] and payload_code and values["货号"].casefold() != payload_code.casefold():
        warnings.append("飞书行款号与商品资料 JSON 款号不一致，本次未合并该 JSON。")
        payload, info = {}, {}
    info = {key: value or text_value(info.get(key)) for key, value in values.items()}
    colors = color_values(find_field(fields, COLOR_FIELDS)) or color_values(payload.get("colors"))
    data = {"info": info, "colors": colors}
    if not any(info.values()) and not colors:
        raise FeishuImportError("已读取该行，但未识别到商品名称、款号、尺码、材质或颜色字段。请核对行号或使用商品资料 JSON。")
    for key, aliases in TABLE_FIELDS.items():
        if isinstance(payload.get(key), dict):
            data[key] = payload[key]
            continue
        normalized = table_value(find_field(fields, aliases), key)
        if normalized:
            data[key] = normalized
        elif key != "try_on":
            warnings.append(f"{aliases[0]}未取得可用数据；如附件是图片，请核对后将数据补入商品资料。")
    products, scenes = image_assignments(attachments, colors, token, cache_dir, warnings)
    data["warnings"] = [*([note for note in payload["warnings"] if isinstance(note, str)] if isinstance(payload.get("warnings"), list) else []), *warnings]
    details = [{"field": field, "name": str(item.get("name", "未命名附件"))} for field, item in attachments]
    source = f"{label} · {clean} · {record['record_id']}"
    return ImportedRow(data, source, str(record["record_id"]), details, products, scenes)
