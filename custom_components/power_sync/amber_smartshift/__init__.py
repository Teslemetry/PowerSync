"""Native Amber Smart Shift battery support."""

BATTERY_SYSTEM = "amber_smartshift"
EMAIL = "amber_smartshift_email"
PASSWORD = "amber_smartshift_password"
SITE = "amber_smartshift_site_id"
CONFIG = "amber_smartshift_config_id"
MANAGED = "amber_smartshift_managed"
ALLOW_ENABLE = "amber_smartshift_allow_enable"
CAPABILITIES = {
    "timed_modes": True,
    "target_charge_power": False,
    "target_export_power": False,
    "backup_reserve": False,
    "solar_curtailment": False,
    "off_grid": False,
}
