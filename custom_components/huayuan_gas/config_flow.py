"""Configuration flow for Huayuan Gas."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GasApi, GasApiError
from .const import CONF_SN, DOMAIN


class HuayuanGasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            sn = user_input[CONF_SN].strip()
            if not sn:
                errors[CONF_SN] = "invalid_sn"
            else:
                if any(
                    entry.data.get(CONF_SN, "").strip() == sn
                    for entry in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(sn)
                self._abort_if_unique_id_configured()
                try:
                    await GasApi(async_get_clientsession(self.hass), sn).balance()
                except GasApiError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title="Huayuan Gas", data={CONF_SN: sn}
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_SN): str}),
            errors=errors,
        )
