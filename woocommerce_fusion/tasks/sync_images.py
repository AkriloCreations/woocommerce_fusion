"""
Push an ERPNext Item's image to WooCommerce as a real Media Library attachment.

ERPNext holds image *URLs* (many are extension-less Shopee CDN links). WooCommerce
rejects a bare `{"src": url}` for those with `woocommerce_product_image_upload_error:
Invalid image`, so we download the bytes, detect the type by magic bytes, upload to
`wp/v2/media`, and send `{"id": attachment_id}` on the product.

A `WooCommerce Media Cache` DocType maps source_url -> attachment_id per server so a
re-sync never creates a duplicate Media Library entry.

Failures are logged and swallowed - a bad image must never abort an item's sync.
"""

import base64
import json
from urllib.parse import urljoin

import frappe
import requests

# Cloudflare returns HTTP 403 (error 1010) for the default python-requests / urllib
# User-Agent, so a custom one is mandatory when fetching from the Shopee CDN.
FETCH_UA = "AkriloSync/1.0 (+ERPNext connector)"


def detect_image_type(blob: bytes) -> tuple[str, str]:
	"""Return (mime, extension) from magic bytes. Raise on anything unrecognised -
	the Shopee URLs carry no extension, so we must never guess."""
	if blob[:2] == b"\xff\xd8":
		return "image/jpeg", "jpg"
	if blob[:8] == b"\x89PNG\r\n\x1a\n":
		return "image/png", "png"
	if blob[:6] in (b"GIF87a", b"GIF89a"):
		return "image/gif", "gif"
	if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
		return "image/webp", "webp"
	raise ValueError("Unrecognised image format (magic bytes %r)" % blob[:12])


def fetch_image(url: str) -> bytes:
	resp = requests.get(url, headers={"User-Agent": FETCH_UA}, timeout=60)
	resp.raise_for_status()
	if not resp.content:
		raise ValueError("Empty response body from %s" % url)
	return resp.content


def get_cached_attachment(source_url: str, server: str) -> str | None:
	return frappe.db.get_value(
		"WooCommerce Media Cache",
		{"source_url": source_url, "woocommerce_server": server},
		"attachment_id",
	)


def cache_attachment(source_url: str, server: str, attachment_id: str, file_type: str) -> None:
	if get_cached_attachment(source_url, server):
		return
	frappe.get_doc(
		{
			"doctype": "WooCommerce Media Cache",
			"source_url": source_url,
			"woocommerce_server": server,
			"attachment_id": str(attachment_id),
			"file_type": file_type,
		}
	).insert(ignore_permissions=True)
	# Commit immediately: the WordPress upload already happened and cannot be
	# rolled back, so the cache row must survive even if the caller's transaction
	# is later rolled back. Without this, every sync re-uploads the same image.
	frappe.db.commit()


def upload_media(blob: bytes, filename: str, mime: str, wc_server) -> str:
	"""POST bytes to wp/v2/media (NOT wc/v3) and return the new attachment id.

	The wp/v2 core REST API does NOT accept the WooCommerce consumer key/secret -
	it authenticates with a WordPress user + Application Password (HTTP 401
	`invalid_username` otherwise). These are separate credentials from the wc/v3
	pair, held in `wp_username` / `wp_application_password` on the server.
	"""
	base = wc_server.woocommerce_server_url.rstrip("/")
	url = urljoin(base + "/", "wp-json/wp/v2/media")

	wp_user = wc_server.get("wp_username")
	wp_pass = wc_server.get_password("wp_application_password", raise_exception=False)
	if not wp_user or not wp_pass:
		raise ValueError(
			"Image push needs WordPress Username and Application Password on the "
			"WooCommerce Server; the consumer key does not authenticate wp/v2/media."
		)
	auth = base64.b64encode(("%s:%s" % (wp_user, wp_pass)).encode()).decode()
	resp = requests.post(
		url,
		data=blob,
		headers={
			"Authorization": "Basic " + auth,
			"User-Agent": FETCH_UA,
			"Content-Type": mime,
			"Content-Disposition": 'attachment; filename="%s"' % filename,
		},
		timeout=90,
	)
	resp.raise_for_status()
	return str(resp.json()["id"])


def resolve_attachment(source_url: str, wc_server) -> str | None:
	"""Return an attachment id for the image URL, uploading and caching on first use.
	Returns None (and logs) on any failure - the caller keeps syncing."""
	if not source_url:
		return None
	server = wc_server.name
	cached = get_cached_attachment(source_url, server)
	if cached:
		return cached
	try:
		blob = fetch_image(source_url)
		mime, ext = detect_image_type(blob)
		attachment_id = upload_media(blob, "item-image.%s" % ext, mime, wc_server)
		cache_attachment(source_url, server, attachment_id, ext)
		return attachment_id
	except Exception:
		frappe.log_error(
			title="WooCommerce image push failed",
			message="URL: %s\n\n%s" % (source_url, frappe.get_traceback()),
		)
		return None


def get_item_image_urls(item) -> list[str]:
	"""All image URLs for an ERPNext Item, main image first: the single `image`
	field plus every `File` attached to it (shopee_bridge saves the full Shopee
	gallery this way - see _attach_multiple_image_files), deduplicated in order."""
	urls = [item.image] if item.image else []
	attached = frappe.get_all(
		"File",
		filters={"attached_to_doctype": item.doctype, "attached_to_name": item.name},
		fields=["file_url"],
		order_by="creation asc",
	)
	for row in attached:
		if row.file_url and row.file_url not in urls:
			urls.append(row.file_url)
	return urls


def apply_image_to_product(wc_product, item, wc_server) -> bool:
	"""Set the product's images to the ERPNext Item's full gallery (main `image`
	field + attached Shopee photos), by attachment id, main image first.
	Returns True if the product's images changed."""
	if not wc_server.get("enable_image_push"):
		return False

	image_urls = get_item_image_urls(item)
	if not image_urls:
		return False

	attachment_ids = [resolve_attachment(url, wc_server) for url in image_urls]
	attachment_ids = [a for a in attachment_ids if a]
	if not attachment_ids:
		return False

	try:
		current = json.loads(wc_product.images) if wc_product.images else []
	except (ValueError, TypeError):
		current = []
	# `images` is a Frappe JSON-type field: an unset value on a freshly-created
	# WooCommerceProduct doc is normalised to the *string* "null" (json.dumps(None)),
	# not Python None or "" -- json.loads("null") parses cleanly to None, which then
	# blows up the list comprehension below. Treat a non-list parse as empty.
	if not isinstance(current, list):
		current = []

	current_ids = [str(c.get("id")) for c in current]
	if current_ids == [str(a) for a in attachment_ids]:
		return False

	wc_product.images = json.dumps([{"id": int(a)} for a in attachment_ids])
	return True
