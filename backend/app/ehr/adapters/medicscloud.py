"""
MedicsCloud EHR Adapter — Playwright browser automation.

MedicsCloud has NO API — we automate the web UI with headless Chromium.
This is specifically for Dr. Stefanides' practice (first client).
"""

import asyncio
import logging
from datetime import date, time, datetime
from typing import Optional

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRAppointment, EHRSlot, EHRProvider,
)

logger = logging.getLogger(__name__)

# CSS selectors — centralized for easy updates when MedicsCloud changes UI
SELECTORS = {
    "login_username": "input[name='username'], #username",
    "login_password": "input[name='password'], #password",
    "login_button": "button[type='submit'], .login-btn",
    "dashboard_indicator": ".dashboard, .main-content, #app",
    "patient_search_input": "input.patient-search, #patient-search",
    "patient_results_table": "table.patient-results tbody tr",
    "new_patient_btn": ".new-patient-btn, a[href*='patient/new']",
    "scheduler_nav": "a[href*='scheduler'], .nav-scheduler",
    "appointment_list": "table.appointments tbody tr",
    "provider_list": "table.providers tbody tr, .provider-list .provider-item",
    "cancel_btn": ".cancel-appointment, button.btn-cancel",
    "confirm_dialog": ".modal-confirm button.btn-primary, .confirm-btn",
}

# Delay between operations to avoid bot detection
OPERATION_DELAY = 2.0


class MedicsCloudAdapter(EHRAdapter):
    """MedicsCloud integration via Playwright browser automation."""

    def __init__(self, **kwargs):
        self.username: str = kwargs.get("username", "")
        self.password: str = kwargs.get("password", "")
        self.base_url: str = kwargs.get("base_url", "https://app.medicscloud.com")
        self._browser = None
        self._context = None
        self._page = None
        self._connected = False

    async def _ensure_playwright(self):
        """Lazy import — playwright is optional and heavy."""
        try:
            from playwright.async_api import async_playwright
            return async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

    async def connect(self, credentials: dict) -> bool:
        self.username = credentials.get("username", self.username)
        self.password = credentials.get("password", self.password)
        if credentials.get("base_url"):
            self.base_url = credentials["base_url"]

        try:
            playwright_cls = await self._ensure_playwright()
            pw = await playwright_cls().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()

            # Navigate to login
            await self._page.goto(self.base_url, wait_until="networkidle")
            await asyncio.sleep(1)

            # Fill login form
            await self._page.fill(SELECTORS["login_username"], self.username)
            await self._page.fill(SELECTORS["login_password"], self.password)
            await self._page.click(SELECTORS["login_button"])

            # Wait for dashboard
            await self._page.wait_for_selector(
                SELECTORS["dashboard_indicator"], timeout=15000
            )

            self._connected = True
            logger.info("Connected to MedicsCloud via Playwright")
            return True

        except Exception as e:
            logger.error("MedicsCloud login failed: %s", e)
            if self._page:
                try:
                    await self._page.screenshot(path="/tmp/medicscloud_login_error.png")
                except Exception:
                    pass
            await self.disconnect()
            return False

    async def disconnect(self) -> bool:
        self._connected = False
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        return True

    async def health_check(self) -> bool:
        if not self._connected or not self._page:
            return False
        try:
            url = self._page.url
            return self.base_url in url
        except Exception:
            return False

    async def search_patients(
        self,
        first_name: str = "",
        last_name: str = "",
        dob: Optional[date] = None,
    ) -> list[EHRPatient]:
        if not self._page:
            return []

        try:
            search_term = f"{last_name}, {first_name}".strip(", ")
            await self._page.goto(
                f"{self.base_url}/patients", wait_until="networkidle"
            )
            await asyncio.sleep(OPERATION_DELAY)

            await self._page.fill(SELECTORS["patient_search_input"], search_term)
            await self._page.keyboard.press("Enter")
            await asyncio.sleep(OPERATION_DELAY)

            # Parse results table
            rows = await self._page.query_selector_all(
                SELECTORS["patient_results_table"]
            )
            patients = []
            for row in rows[:20]:  # Limit to 20 results
                cells = await row.query_selector_all("td")
                if len(cells) >= 3:
                    name_text = await cells[0].inner_text()
                    dob_text = await cells[1].inner_text()
                    phone_text = await cells[2].inner_text() if len(cells) > 2 else ""

                    # Parse name
                    parts = name_text.split(",", 1)
                    p_last = parts[0].strip() if parts else ""
                    p_first = parts[1].strip() if len(parts) > 1 else ""

                    # Parse DOB
                    try:
                        p_dob = datetime.strptime(dob_text.strip(), "%m/%d/%Y").date()
                    except ValueError:
                        p_dob = date.today()

                    # Get row ID from data attribute or link
                    row_id = await row.get_attribute("data-id") or ""

                    patients.append(
                        EHRPatient(
                            ehr_id=row_id,
                            first_name=p_first,
                            last_name=p_last,
                            dob=p_dob,
                            phone=phone_text.strip(),
                        )
                    )
            return patients

        except Exception as e:
            logger.error("MedicsCloud patient search failed: %s", e)
            await self._screenshot_on_error("patient_search")
            return []

    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        if not self._page:
            raise RuntimeError("Not connected")

        try:
            await self._page.goto(
                f"{self.base_url}/patients/new", wait_until="networkidle"
            )
            await asyncio.sleep(OPERATION_DELAY)

            await self._page.fill("input[name='first_name']", patient.first_name)
            await self._page.fill("input[name='last_name']", patient.last_name)
            await self._page.fill(
                "input[name='dob']", patient.dob.strftime("%m/%d/%Y")
            )
            if patient.phone:
                await self._page.fill("input[name='phone']", patient.phone)
            if patient.email:
                await self._page.fill("input[name='email']", patient.email)

            await self._page.click("button[type='submit']")
            await asyncio.sleep(OPERATION_DELAY)

            # Try to extract new patient ID from URL or page
            url = self._page.url
            if "/patients/" in url:
                patient.ehr_id = url.split("/patients/")[-1].split("/")[0]

            logger.info("MedicsCloud patient created: %s", patient.ehr_id)
            return patient

        except Exception as e:
            logger.error("MedicsCloud create patient failed: %s", e)
            await self._screenshot_on_error("create_patient")
            raise

    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        if not self._page:
            raise RuntimeError("Not connected")

        try:
            await self._page.goto(
                f"{self.base_url}/patients/{patient.ehr_id}/edit",
                wait_until="networkidle",
            )
            await asyncio.sleep(OPERATION_DELAY)

            await self._page.fill("input[name='first_name']", patient.first_name)
            await self._page.fill("input[name='last_name']", patient.last_name)
            if patient.phone:
                await self._page.fill("input[name='phone']", patient.phone)

            await self._page.click("button[type='submit']")
            await asyncio.sleep(OPERATION_DELAY)
            return patient

        except Exception as e:
            logger.error("MedicsCloud update patient failed: %s", e)
            await self._screenshot_on_error("update_patient")
            raise

    async def get_available_slots(
        self,
        provider_id: str,
        target_date: date,
        appointment_type: str = "",
    ) -> list[EHRSlot]:
        if not self._page:
            return []

        try:
            date_str = target_date.strftime("%Y-%m-%d")
            await self._page.goto(
                f"{self.base_url}/scheduler?date={date_str}&provider={provider_id}",
                wait_until="networkidle",
            )
            await asyncio.sleep(OPERATION_DELAY)

            # Read open slots from calendar grid
            slot_elements = await self._page.query_selector_all(
                ".time-slot.available, .slot-open"
            )
            slots = []
            for elem in slot_elements:
                time_text = await elem.get_attribute("data-time") or await elem.inner_text()
                try:
                    slot_time = datetime.strptime(time_text.strip(), "%I:%M %p").time()
                except ValueError:
                    try:
                        slot_time = datetime.strptime(time_text.strip(), "%H:%M").time()
                    except ValueError:
                        continue

                duration = int(await elem.get_attribute("data-duration") or "30")

                slots.append(
                    EHRSlot(
                        date=target_date,
                        time=slot_time,
                        duration_minutes=duration,
                        provider_ehr_id=provider_id,
                        is_available=True,
                    )
                )
            return slots

        except Exception as e:
            logger.error("MedicsCloud get slots failed: %s", e)
            await self._screenshot_on_error("get_slots")
            return []

    async def book_appointment(
        self,
        patient_id: str,
        slot: EHRSlot,
        appointment_type: str,
        notes: str = "",
    ) -> EHRAppointment:
        if not self._page:
            raise RuntimeError("Not connected")

        try:
            date_str = slot.date.strftime("%Y-%m-%d")
            time_str = slot.time.strftime("%H:%M")

            await self._page.goto(
                f"{self.base_url}/scheduler?date={date_str}&provider={slot.provider_ehr_id}",
                wait_until="networkidle",
            )
            await asyncio.sleep(OPERATION_DELAY)

            # Click the time slot
            slot_selector = f".time-slot[data-time='{time_str}']"
            await self._page.click(slot_selector)
            await asyncio.sleep(1)

            # Fill patient info in booking dialog
            await self._page.fill("input[name='patient_id']", patient_id)
            if appointment_type:
                try:
                    await self._page.select_option(
                        "select[name='appointment_type']", appointment_type
                    )
                except Exception:
                    pass
            if notes:
                await self._page.fill("textarea[name='notes']", notes)

            await self._page.click("button.book-btn, button[type='submit']")
            await asyncio.sleep(OPERATION_DELAY)

            # Extract appointment ID
            appt_id = ""
            url = self._page.url
            if "/appointments/" in url:
                appt_id = url.split("/appointments/")[-1].split("/")[0]

            return EHRAppointment(
                ehr_id=appt_id,
                patient_ehr_id=patient_id,
                provider_ehr_id=slot.provider_ehr_id,
                appointment_type=appointment_type,
                date=slot.date,
                time=slot.time,
                duration_minutes=slot.duration_minutes,
                status="booked",
                notes=notes,
            )

        except Exception as e:
            logger.error("MedicsCloud book appointment failed: %s", e)
            await self._screenshot_on_error("book_appointment")
            raise

    async def cancel_appointment(self, appointment_id: str) -> bool:
        if not self._page:
            return False

        try:
            await self._page.goto(
                f"{self.base_url}/appointments/{appointment_id}",
                wait_until="networkidle",
            )
            await asyncio.sleep(OPERATION_DELAY)

            await self._page.click(SELECTORS["cancel_btn"])
            await asyncio.sleep(1)

            # Confirm cancellation dialog
            await self._page.click(SELECTORS["confirm_dialog"])
            await asyncio.sleep(OPERATION_DELAY)

            logger.info("MedicsCloud appointment %s cancelled", appointment_id)
            return True

        except Exception as e:
            logger.error("MedicsCloud cancel failed: %s", e)
            await self._screenshot_on_error("cancel_appointment")
            return False

    async def get_appointments(
        self,
        provider_id: str = "",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[EHRAppointment]:
        if not self._page:
            return []

        try:
            url = f"{self.base_url}/appointments"
            params = []
            if provider_id:
                params.append(f"provider={provider_id}")
            if start_date:
                params.append(f"from={start_date.isoformat()}")
            if end_date:
                params.append(f"to={end_date.isoformat()}")
            if params:
                url += "?" + "&".join(params)

            await self._page.goto(url, wait_until="networkidle")
            await asyncio.sleep(OPERATION_DELAY)

            rows = await self._page.query_selector_all(SELECTORS["appointment_list"])
            appointments = []
            for row in rows[:50]:
                cells = await row.query_selector_all("td")
                if len(cells) < 4:
                    continue

                date_text = await cells[0].inner_text()
                time_text = await cells[1].inner_text()
                patient_text = await cells[2].inner_text()
                status_text = await cells[3].inner_text()
                row_id = await row.get_attribute("data-id") or ""

                try:
                    appt_date = datetime.strptime(date_text.strip(), "%m/%d/%Y").date()
                    appt_time = datetime.strptime(time_text.strip(), "%I:%M %p").time()
                except ValueError:
                    continue

                appointments.append(
                    EHRAppointment(
                        ehr_id=row_id,
                        patient_ehr_id="",
                        provider_ehr_id=provider_id,
                        appointment_type="",
                        date=appt_date,
                        time=appt_time,
                        duration_minutes=30,
                        status=status_text.strip().lower(),
                    )
                )
            return appointments

        except Exception as e:
            logger.error("MedicsCloud get appointments failed: %s", e)
            await self._screenshot_on_error("get_appointments")
            return []

    async def get_providers(self) -> list[EHRProvider]:
        if not self._page:
            return []

        try:
            await self._page.goto(
                f"{self.base_url}/providers", wait_until="networkidle"
            )
            await asyncio.sleep(OPERATION_DELAY)

            rows = await self._page.query_selector_all(SELECTORS["provider_list"])
            providers = []
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    name_text = await row.inner_text()
                    row_id = await row.get_attribute("data-id") or ""
                    providers.append(
                        EHRProvider(ehr_id=row_id, name=name_text.strip())
                    )
                else:
                    name_text = await cells[0].inner_text()
                    specialty = await cells[1].inner_text() if len(cells) > 1 else ""
                    npi = await cells[2].inner_text() if len(cells) > 2 else ""
                    row_id = await row.get_attribute("data-id") or ""

                    providers.append(
                        EHRProvider(
                            ehr_id=row_id,
                            name=name_text.strip(),
                            npi=npi.strip() or None,
                            specialty=specialty.strip() or None,
                        )
                    )
            return providers

        except Exception as e:
            logger.error("MedicsCloud get providers failed: %s", e)
            await self._screenshot_on_error("get_providers")
            return []

    async def get_appointment_types(self) -> list[dict]:
        """MedicsCloud appointment types are usually limited — return empty."""
        return []

    async def _screenshot_on_error(self, operation: str) -> None:
        """Take a screenshot for debugging when an operation fails."""
        if self._page:
            try:
                path = f"/tmp/medicscloud_{operation}_error.png"
                await self._page.screenshot(path=path)
                logger.info("Error screenshot saved: %s", path)
            except Exception:
                pass
