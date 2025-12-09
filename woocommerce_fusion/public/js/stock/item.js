// Helper to show variant selection dialog and run sync_template_variants
const show_variant_sync_dialog = (frm) => {
	frappe.call({
		method: "woocommerce_fusion.tasks.sync_items.get_variants_with_attributes",
		args: { template_item_code: frm.doc.name }
	}).then(res => {
		const data = (res && res.message && res.message.variants) ? res.message.variants : [];
		if (!data.length) {
			frappe.show_alert({ message: __('No variants found to sync'), indicator: 'orange' }, 5);
			return;
		}

		const variantAttrMap = {};

		data.forEach(v => {
			variantAttrMap[v.name] = v.attributes || [];
		});

		const variant_names = data.map(v => v.name);
		const variant_options = variant_names.map(name => ({ label: name, value: name, checked: true }));

		// Build attribute options (use template attributes if present, else from variants)
		const attr_set = new Set();
		(frm.doc.attributes || []).forEach(a => attr_set.add(a.attribute));
		if (attr_set.size === 0) {
			data.forEach(v => (v.attributes || []).forEach(a => attr_set.add(a)));
		}
		const attr_options = Array.from(attr_set).map(a => ({ label: a, value: a, checked: true }));

		const d = new frappe.ui.Dialog({
			title: __('Select Variants to Sync'),
			fields: [
				{
					fieldname: 'attr_filter',
					fieldtype: 'MultiCheck',
					label: __('Filter by Attributes'),
					options: attr_options,
					description: __('Select attributes that must be present on the variant')
				},
				{
					fieldname: 'variants',
					fieldtype: 'MultiCheck',
					label: __('Variants'),
					options: variant_options,
					description: __('Leave all checked to sync all variants')
				}
			],
			primary_action_label: __('Sync'),
			primary_action: (values) => {
				const selectedAttrs = (values.attr_filter || []).filter(v => v);
				const selectedVariants = (values.variants || []).filter(v => v);

				const filteredByAttrs = variant_names.filter(name => {
					if (!selectedAttrs.length) return true;
					const attrs = variantAttrMap[name] || [];
					return selectedAttrs.every(a => attrs.includes(a));
				});

				const finalVariants = filteredByAttrs.filter(name => {
					if (!selectedVariants.length) return true;
					return selectedVariants.includes(name);
				});

				if (!finalVariants.length) {
					frappe.show_alert({ message: __('No variants match the selection'), indicator: 'orange' }, 5);
					return;
				}

				d.hide();
				frappe.dom.freeze(__("Syncing Selected Variants to WooCommerce..."));
				frappe.call({
					method: "woocommerce_fusion.tasks.sync_items.sync_template_variants",
					args: {
						item_code: frm.doc.name,
						variant_codes: finalVariants,
						enqueue: false
					},
					callback: function (r) {
						frappe.dom.unfreeze();
						frappe.show_alert({
							message: __('Template and selected variants synced'),
							indicator: 'green'
						}, 5);
						frm.reload_doc();
					},
					error: (r) => {
						frappe.dom.unfreeze();
						let msg = __('There was an error processing the request. See Error Log.');
						if (r && r.exc) {
							msg = r.exc;
						} else if (r && r.message) {
							msg = r.message;
						}
						frappe.msgprint(msg);
					}
				});
			}
		});

		d.show();
	});
};

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
		// If template, show SKU picker (will sync template + selected variants)
		if (frm.doc.has_variants && !frm.doc.variant_of) {
			show_variant_sync_dialog(frm);
			return;
		}

		// Sync this Item
		frappe.dom.freeze(__("Sync Item with WooCommerce..."));
		const method = (frm.doc.has_variants && !frm.doc.variant_of)
			? "woocommerce_fusion.tasks.sync_items.sync_template_variants"
			: "woocommerce_fusion.tasks.sync_items.run_item_sync";
		frappe.call({
			method: method,
			args: {
				item_code: frm.doc.name,
				enqueue: false
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
				let msg = __('There was an error processing the request. See Error Log.');
				if (r && r.exc) {
					msg = r.exc;
				} else if (r && r.message) {
					msg = r.message;
				}
				frappe.msgprint(msg);
			}
		});
	},

	sync_all_variants: function (frm) {
		// Let user choose which variants (SKUs) to sync
		show_variant_sync_dialog(frm);
	},
})

frappe.ui.form.on('Item WooCommerce Server', {
	view_product: function (frm, cdt, cdn) {
		let current_row_doc = locals[cdt][cdn];
		console.log(current_row_doc);
		frappe.set_route("Form", "WooCommerce Product", `${current_row_doc.woocommerce_server}~${current_row_doc.woocommerce_id}`);
	}
})
