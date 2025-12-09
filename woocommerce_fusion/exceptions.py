from frappe.exceptions import ValidationError


class SyncDisabledError(ValidationError):
	pass



class WooCommerceOrderNotFoundError(ValidationError):
	pass


class WooCommerceError(ValidationError):
	pass
