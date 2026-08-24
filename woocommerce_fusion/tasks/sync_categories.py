"""
Map an ERPNext Item Group to a WooCommerce product category.

ERPNext is the source of truth for how the catalog is organised, so the Item
Group a template sits in decides its storefront category. The category is
created in WooCommerce on first use and then reused, keyed by slug.

Only groups *below* the configured `item_group` are mapped - that setting names
the root of the sellable catalog, which is not itself a category.
"""

import json
import re

import frappe

from woocommerce_fusion.tasks.utils import APIWithRequestLogging


def slugify(name: str) -> str:
	"""ASCII slug. `frappe.utils.slug` keeps `&`, which is not a valid slug
	character - "Rak & Display" would become "rak-&-display"."""
	return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def _wc_api(wc_server):
	return APIWithRequestLogging(
		url=wc_server.woocommerce_server_url,
		consumer_key=wc_server.api_consumer_key,
		consumer_secret=wc_server.api_consumer_secret,
		version="wc/v3",
		timeout=40,
	)


def get_or_create_category(name: str, wc_server) -> int | None:
	"""Return the WooCommerce category id for `name`, creating it if absent."""
	api = _wc_api(wc_server)
	target = slugify(name)

	res = api.get("products/categories", params={"slug": target, "per_page": 1})
	if res.status_code == 200 and res.json():
		return res.json()[0]["id"]

	res = api.post("products/categories", data={"name": name, "slug": target})
	if res.status_code in (200, 201):
		return res.json()["id"]

	# Someone else created it between our GET and POST, or the slug collided.
	if res.status_code == 400:
		res = api.get("products/categories", params={"slug": target, "per_page": 1})
		if res.status_code == 200 and res.json():
			return res.json()[0]["id"]

	frappe.log_error(
		title="WooCommerce category sync failed",
		message="name=%s slug=%s status=%s body=%s" % (name, target, res.status_code, res.text[:500]),
	)
	return None


def apply_category_to_product(wc_product, item, wc_server) -> bool:
	"""Set the product's category from the Item's Item Group.

	Returns True when the product changed. A variation inherits its parent's
	category in WooCommerce, so only the main product carries one.
	"""
	if not wc_server.get("enable_category_sync") or item.get("variant_of"):
		return False

	group = item.get("item_group")
	# The configured root is the catalog itself, not a category within it.
	if not group or group == wc_server.item_group:
		return False

	category_id = get_or_create_category(group, wc_server)
	if not category_id:
		return False

	try:
		current = json.loads(wc_product.categories) if wc_product.categories else []
	except (ValueError, TypeError):
		current = []
	# `categories` is a Frappe JSON-type field: an unset value on a freshly-created
	# WooCommerceProduct doc is normalised to the *string* "null" (json.dumps(None)),
	# not Python None or "" -- json.loads("null") parses cleanly to None, which then
	# breaks the `any(...)` iteration below. Same root cause as sync_images.py.
	if not isinstance(current, list):
		current = []

	if any(c.get("id") == category_id for c in current):
		return False

	wc_product.categories = json.dumps([{"id": category_id}])
	return True
