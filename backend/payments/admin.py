# backend/payments/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import PaymentTransaction, Subscription

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_user_or_email', 'amount', 'currency', 'payment_gateway', 'gateway_transaction_id_short', 'status', 'created_at_formatted')
    list_filter = ('payment_gateway', 'status', 'currency', 'created_at')
    search_fields = ('id__iexact', 'user__username', 'user__email', 'email_for_guest', 'gateway_transaction_id', 'papri_internal_reference', 'description')
    readonly_fields = ('id', 'user', 'email_for_guest', 'amount', 'currency', 'payment_gateway', 
                       'gateway_transaction_id', 'papri_internal_reference', 'status', 
                       'gateway_response_data_pretty', 'metadata_pretty',
                       'created_at', 'updated_at')
    fieldsets = (
        ("Transaction Overview", {'fields': ('id', 'user', 'email_for_guest', 'status', 'payment_gateway')}),
        ("Amount & Details", {'fields': ('amount', 'currency', 'description', 'gateway_transaction_id', 'papri_internal_reference')}),
        ("Gateway Data", {'fields': ('gateway_response_data_pretty', 'metadata_pretty')}),
        ("Timestamps", {'fields': ('created_at', 'updated_at')}),
    )
    list_per_page = 25
    ordering = ('-created_at',)

    def linked_user_or_email(self, obj):
        if obj.user:
            link = reverse("admin:auth_user_change", args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', link, obj.user.username)
        return obj.email_for_guest or "N/A (Guest)"
    linked_user_or_email.short_description = "User/Email"
    linked_user_or_email.admin_order_field = 'user__username' # Allow sorting by username

    def gateway_transaction_id_short(self, obj):
        if obj.gateway_transaction_id:
            return (obj.gateway_transaction_id[:20] + '...') if len(obj.gateway_transaction_id) > 20 else obj.gateway_transaction_id
        return "N/A"
    gateway_transaction_id_short.short_description = "Gateway Ref"
    
    def created_at_formatted(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M") if obj.created_at else "N/A"
    created_at_formatted.admin_order_field = 'created_at'
    created_at_formatted.short_description = 'Timestamp'

    def _pretty_json_field_admin(self, obj_json_field):
        if obj_json_field:
            try:
                import json
                pretty_json = json.dumps(obj_json_field, indent=2, sort_keys=True)
                return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
            except TypeError: return str(obj_json_field)
        return "N/A"

    def gateway_response_data_pretty(self, obj):
        return self._pretty_json_field_admin(obj.gateway_response_data)
    gateway_response_data_pretty.short_description = "Gateway Response (JSON)"

    def metadata_pretty(self, obj):
        return self._pretty_json_field_admin(obj.metadata)
    metadata_pretty.short_description = "Additional Metadata (JSON)"

    # Disable add permission if transactions are always created programmatically
    # def has_add_permission(self, request):
    #     return False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_user_subscription', 'plan_name', 'status', 'start_date_formatted', 'end_date_formatted', 'auto_renew', 'gateway_subscription_id_short')
    list_filter = ('plan_name', 'status', 'auto_renew', 'start_date', 'end_date')
    search_fields = ('id__iexact', 'user__username', 'user__email', 'gateway_subscription_id')
    raw_id_fields = ('user', 'activating_transaction') # For performance if many users/transactions
    readonly_fields = ('id', 'created_at', 'updated_at', 'cancelled_at')
    fieldsets = (
        ("Subscription Core", {'fields': ('id', 'user', 'plan_name', 'status')}),
        ("Dates & Duration", {'fields': ('start_date', 'end_date', 'auto_renew', 'cancelled_at')}),
        ("Gateway & Activation", {'fields': ('gateway_subscription_id', 'activating_transaction')}),
        ("Admin Notes", {'fields': ('notes',)}),
        ("Timestamps", {'fields': ('created_at', 'updated_at')}),
    )
    list_select_related = ('user',) # Optimize query for user display
    list_per_page = 25
    ordering = ('-start_date',)
    actions = ['mark_as_active', 'mark_as_expired', 'cancel_subscription_admin']

    def linked_user_subscription(self, obj):
        if obj.user:
            link = reverse("admin:auth_user_change", args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', link, obj.user.username)
        return "N/A"
    linked_user_subscription.short_description = "User"
    linked_user_subscription.admin_order_field = 'user__username'

    def gateway_subscription_id_short(self, obj):
        if obj.gateway_subscription_id:
            return (obj.gateway_subscription_id[:20] + '...') if len(obj.gateway_subscription_id) > 20 else obj.gateway_subscription_id
        return "N/A"
    gateway_subscription_id_short.short_description = "Gateway Sub ID"

    def _format_date_admin(self, date_obj):
        return date_obj.strftime("%Y-%m-%d") if date_obj else "N/A"
    
    def start_date_formatted(self, obj): return self._format_date_admin(obj.start_date)
    start_date_formatted.admin_order_field = 'start_date'
    start_date_formatted.short_description = 'Starts'

    def end_date_formatted(self, obj): return self._format_date_admin(obj.end_date)
    end_date_formatted.admin_order_field = 'end_date'
    end_date_formatted.short_description = 'Ends'

    # Admin Actions (use with caution, ensure business logic is handled)
    def mark_as_active(self, request, queryset):
        # This is a simplified action; real activation might involve UserProfile updates.
        updated_count = queryset.update(status='active', end_date=None) # Example: make it ongoing
        self.message_user(request, f"{updated_count} subscriptions marked as active.")
    mark_as_active.short_description = "Mark selected subscriptions as ACTIVE"

    def mark_as_expired(self, request, queryset):
        updated_count = queryset.update(status='expired', end_date=timezone.now())
        self.message_user(request, f"{updated_count} subscriptions marked as expired.")
    mark_as_expired.short_description = "Mark selected subscriptions as EXPIRED"
    
    def cancel_subscription_admin(self, request, queryset):
        # This only updates DB status; actual gateway cancellation needs separate logic.
        updated_count = queryset.update(status='cancelled_by_user', cancelled_at=timezone.now(), auto_renew=False)
        self.message_user(request, f"{updated_count} subscriptions marked as cancelled by admin.")
    cancel_subscription_admin.short_description = "Cancel selected subscriptions (Admin Action)"
