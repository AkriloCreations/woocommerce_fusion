frappe.ui.form.on('Item', {
	refresh: function (frm) {
		// Add a custom button to sync Item Stock with WooCommerce
		frm.add_custom_button(__("Sync this Item's Stock Levels to WooCommerce"), function () {
			frm.trigger("sync_item_stock");
		}, __('Actions'));

		// Add a custom button to sync Item Price with WooCommerce
		frm.add_custom_button(__("Sync this Item's Price to WooCommerce"), function () {
			frm.trigger("sync_item_price");
		}, __('Actions'));

		// Add sync button for all items
		frm.add_custom_button(__("Sync this Item with WooCommerce"), function () {
			frm.trigger("sync_item");
		}, __('Actions'));

		// Add extra button for template items to sync all variants
		if (frm.doc.has_variants) {
			frm.add_custom_button(__("Sync All Variants"), function () {
				frm.trigger("sync_all_variants");
			}, __('Actions'));
		}
	},

	sync_item_stock: function (frm) {
		// Sync this Item
		frappe.dom.freeze(__("Sync Item Stock with WooCommerce..."));
		frappe.call({
			method: "woocommerce_fusion.tasks.stock_update.update_stock_levels_on_woocommerce_site",
			args: {
				item_code: frm.doc.name
			},
			callback: function (r) {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('Synchronised stock level to WooCommerce for enabled servers'),
					indicator: 'green'
				}, 5);
				frm.reload_doc();
			},
			error: (r) => {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('There was an error processing the request. See Error Log.'),
					indicator: 'red'
				}, 5);
			}
		});
	},

	sync_item_price: function (frm) {
		// Sync this Item's Price
		frappe.dom.freeze(__("Sync Item Price with WooCommerce..."));
		frappe.call({
			method: "woocommerce_fusion.tasks.sync_item_prices.run_item_price_sync",
			args: {
				item_code: frm.doc.name
			},
			callback: function (r) {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('Synchronised item price to WooCommerce'),
					indicator: 'green'
				}, 5);
				frm.reload_doc();
			},
			error: (r) => {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('There was an error processing the request. See Error Log.'),
					indicator: 'red'
				}, 5);
			}
		});
	},

	sync_item: function (frm) {
		// Sync this Item
		frappe.dom.freeze(__("Sync Item with WooCommerce..."));
		const method = (frm.doc.has_variants && !frm.doc.variant_of)
			? "woocommerce_fusion.tasks.sync_items.sync_template_variants"
			: "woocommerce_fusion.tasks.sync_items.run_item_sync";
		frappe.call({
			method: method,
			args: {
				item_code: frm.doc.name,
				enqueue: true
			},
			callback: function (r) {
				frappe.dom.unfreeze();
				const msg = method === "woocommerce_fusion.tasks.sync_items.sync_template_variants"
					? __('Template and variants sync enqueued')
					: __('Sync completed successfully');
				frappe.show_alert({ message: msg, indicator: 'green' }, 5);
				frm.reload_doc();
			},
			error: (r) => {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('There was an error processing the request. See Error Log.'),
					indicator: 'red'
				}, 5);
			}
		});
	},

	sync_all_variants: function (frm) {
		// Sync all variants of this template item
		frappe.dom.freeze(__("Syncing All Variants to WooCommerce..."));
		frappe.call({
			method: "woocommerce_fusion.tasks.sync_items.sync_template_variants",
			args: {
				item_code: frm.doc.name,
				enqueue: true
			},
			callback: function (r) {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('Template and variants sync enqueued'),
					indicator: 'green'
				}, 5);
				frm.reload_doc();
			},
			error: (r) => {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __('There was an error processing the request. See Error Log.'),
					indicator: 'red'
				}, 5);
			}
		});
	},
})

frappe.ui.form.on('Item WooCommerce Server', {
	view_product: function (frm, cdt, cdn) {
		let current_row_doc = locals[cdt][cdn];
		console.log(current_row_doc);
		frappe.set_route("Form", "WooCommerce Product", `${current_row_doc.woocommerce_server}~${current_row_doc.woocommerce_id}`);
	}
})
