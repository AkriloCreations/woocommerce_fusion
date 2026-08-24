import json
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase
from frappe import _dict

from woocommerce_fusion.tasks.sync_images import apply_image_to_product, get_item_image_urls


class TestGetItemImageUrls(FrappeTestCase):
	@patch("woocommerce_fusion.tasks.sync_images.frappe.get_all")
	def test_main_image_first_then_attachments_deduplicated(self, mock_get_all):
		item = MagicMock(doctype="Item", name="ITEM-1", image="https://cdn/main.jpg")
		mock_get_all.return_value = [
			_dict(file_url="https://cdn/main.jpg"),  # duplicate of main image, dropped
			_dict(file_url="https://cdn/second.jpg"),
			_dict(file_url="https://cdn/third.jpg"),
		]

		urls = get_item_image_urls(item)

		self.assertEqual(
			urls, ["https://cdn/main.jpg", "https://cdn/second.jpg", "https://cdn/third.jpg"]
		)

	@patch("woocommerce_fusion.tasks.sync_images.frappe.get_all")
	def test_no_main_image_falls_back_to_attachments_only(self, mock_get_all):
		item = MagicMock(doctype="Item", name="ITEM-2", image=None)
		mock_get_all.return_value = [_dict(file_url="https://cdn/only.jpg")]

		self.assertEqual(get_item_image_urls(item), ["https://cdn/only.jpg"])


class TestApplyImageToProduct(FrappeTestCase):
	@patch("woocommerce_fusion.tasks.sync_images.resolve_attachment")
	@patch("woocommerce_fusion.tasks.sync_images.get_item_image_urls")
	def test_pushes_all_images_in_order(self, mock_get_urls, mock_resolve):
		mock_get_urls.return_value = ["https://cdn/a.jpg", "https://cdn/b.jpg"]
		mock_resolve.side_effect = ["101", "102"]
		wc_server = MagicMock(**{"get.return_value": True})
		wc_product = MagicMock(images=None)
		item = MagicMock()

		changed = apply_image_to_product(wc_product, item, wc_server)

		self.assertTrue(changed)
		self.assertEqual(json.loads(wc_product.images), [{"id": 101}, {"id": 102}])

	@patch("woocommerce_fusion.tasks.sync_images.resolve_attachment")
	@patch("woocommerce_fusion.tasks.sync_images.get_item_image_urls")
	def test_noop_when_ids_already_match(self, mock_get_urls, mock_resolve):
		mock_get_urls.return_value = ["https://cdn/a.jpg", "https://cdn/b.jpg"]
		mock_resolve.side_effect = ["101", "102"]
		wc_server = MagicMock(**{"get.return_value": True})
		wc_product = MagicMock(images=json.dumps([{"id": 101}, {"id": 102}]))
		item = MagicMock()

		changed = apply_image_to_product(wc_product, item, wc_server)

		self.assertFalse(changed)

	@patch("woocommerce_fusion.tasks.sync_images.get_item_image_urls")
	def test_noop_when_image_push_disabled(self, mock_get_urls):
		wc_server = MagicMock(**{"get.return_value": False})
		changed = apply_image_to_product(MagicMock(), MagicMock(), wc_server)

		self.assertFalse(changed)
		mock_get_urls.assert_not_called()

	@patch("woocommerce_fusion.tasks.sync_images.resolve_attachment")
	@patch("woocommerce_fusion.tasks.sync_images.get_item_image_urls")
	def test_pushes_images_when_wc_product_images_is_the_string_null(self, mock_get_urls, mock_resolve):
		"""Regression test: a brand-new WooCommerce Product doc's `images` JSON field
		defaults to the *string* "null" (json.dumps(None)), not Python None or "" --
		this used to crash the list comprehension in apply_image_to_product with
		TypeError: 'NoneType' object is not iterable, on every product creation."""
		mock_get_urls.return_value = ["https://cdn/a.jpg"]
		mock_resolve.side_effect = ["101"]
		wc_server = MagicMock(**{"get.return_value": True})
		wc_product = MagicMock(images="null")
		item = MagicMock()

		changed = apply_image_to_product(wc_product, item, wc_server)

		self.assertTrue(changed)
		self.assertEqual(json.loads(wc_product.images), [{"id": 101}])
