"""Config flow for the Bali Blinds integration."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BaliAPI, BaliAuthError, BaliConnectionError
from .const import CONF_GATEWAY_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_GATEWAY_ID): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    api = BaliAPI(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        session=session,
        gateway_id=data.get(CONF_GATEWAY_ID),
    )

    # Test authentication
    await api.authenticate()

    # Get gateway ID for unique ID
    gateway_id = data.get(CONF_GATEWAY_ID, "auto")
    if api._auth_data:
        gateway_id = api._auth_data.device_id

    return {"title": "Bali Blinds", "gateway_id": gateway_id}


class BaliBlindConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bali Blinds."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except BaliConnectionError:
                errors["base"] = "cannot_connect"
            except BaliAuthError:
                errors["base"] = "invalid_auth"
            except ClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Set unique ID based on gateway ID
                await self.async_set_unique_id(info["gateway_id"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
