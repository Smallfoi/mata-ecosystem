"""Доступы сотрудников (S-12).

Половина тестов здесь — про попытки обойти защиту: подставить чужой id, зайти по
прямой ссылке мимо меню, переиграть уровень через форму, подобрать приглашение.
Именно так эти системы и ломают, поэтому проверяем не «работает ли», а «не
работает ли то, что не должно».
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from staff.access import can, levels_for, visible_tabs
from staff.models import (LEVEL_EDIT, LEVEL_FULL, LEVEL_NONE, LEVEL_VIEW,
                          StaffAudit, StaffProfile, TabPermission)


def _device(user):
    """Подтверждённый второй фактор — иначе онбординг уводит на привязку."""
    from django_otp.plugins.otp_totp.models import TOTPDevice
    return TOTPDevice.objects.create(user=user, name="test", confirmed=True)


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_superuser("owner", "o@t.dev", "OwnerPass!2026")
        self.staff = User.objects.create_user("worker@t.dev", "worker@t.dev",
                                              "WorkerPass!2026", is_staff=True)
        self.profile = StaffProfile.objects.create(user=self.staff, full_name="Иван Петров")
        # Второй фактор подключён — иначе онбординг уводил бы на привязку.
        self.staff_device = _device(self.staff)
        self.owner_device = _device(self.owner)

    def _login(self, user, device):
        """Вход + отметка, что код второго фактора уже введён (как после /admin/2fa/)."""
        from django_otp import DEVICE_ID_SESSION_KEY

        self.client.force_login(user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def login_owner(self):
        self._login(self.owner, self.owner_device)

    def login_staff(self):
        self._login(self.staff, self.staff_device)

    def grant(self, tab, level):
        TabPermission.objects.update_or_create(user=self.staff, tab=tab,
                                               defaults={"level": level})


class TabAccessTests(Base):
    """Страница открывается ровно тем, кому выдали вкладку."""

    def test_page_closed_without_right(self):
        self.login_staff()
        for url in ("/admin/1c-log/", "/admin/merch/", "/admin/errors/", "/admin/storage/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_page_opens_with_right(self):
        self.grant("onec_log", LEVEL_VIEW)
        self.login_staff()
        self.assertEqual(self.client.get("/admin/1c-log/").status_code, 200)

    def test_view_level_cannot_change_anything(self):
        """«Смотреть» открывает страницу, но не даёт править — проверяем на Конструкторе."""
        self.grant("merch", LEVEL_VIEW)
        self.login_staff()
        self.assertEqual(self.client.get("/admin/merch/").status_code, 200)
        r = self.client.post("/admin/merch/reorder",
                             data='{"platform":"site","order":[]}',
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_edit_level_can_change(self):
        self.grant("merch", LEVEL_EDIT)
        self.login_staff()
        r = self.client.post("/admin/merch/reorder",
                             data='{"platform":"site","order":[]}',
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)

    def test_one_tab_does_not_open_the_others(self):
        """Выдали одну вкладку — остальные закрыты, в том числе по прямой ссылке."""
        self.grant("onec_log", LEVEL_FULL)
        self.login_staff()
        self.assertEqual(self.client.get("/admin/1c-log/").status_code, 200)
        self.assertEqual(self.client.get("/admin/merch/").status_code, 403)
        self.assertEqual([t.key for t in visible_tabs(self.staff)], ["onec_log"])

    def test_deactivated_staff_loses_everything(self):
        self.grant("onec_log", LEVEL_FULL)
        self.staff.is_active = False
        self.staff.save(update_fields=["is_active"])
        self.assertFalse(can(self.staff, "onec_log"))
        self.assertEqual(levels_for(self.staff), {})


class ModelPermissionTests(Base):
    """Уровень вкладки превращается в права Django — ими гейтятся списки моделей."""

    def _perms(self):
        self.staff = User.objects.get(pk=self.staff.pk)   # сбросить кэш прав
        return self.staff.get_all_permissions()

    def test_no_tab_no_permissions(self):
        self.assertNotIn("catalog.view_product", self._perms())

    def test_view_gives_only_view(self):
        self.grant("catalog.products", LEVEL_VIEW)
        perms = self._perms()
        self.assertIn("catalog.view_product", perms)
        self.assertNotIn("catalog.change_product", perms)
        self.assertNotIn("catalog.delete_product", perms)

    def test_edit_gives_change_but_not_delete(self):
        self.grant("catalog.products", LEVEL_EDIT)
        perms = self._perms()
        self.assertIn("catalog.change_product", perms)
        self.assertIn("catalog.add_product", perms)
        self.assertNotIn("catalog.delete_product", perms)

    def test_full_gives_delete(self):
        self.grant("catalog.products", LEVEL_FULL)
        self.assertIn("catalog.delete_product", self._perms())

    def test_group_tab_covers_all_its_models(self):
        """Вкладка «Клубы» закрывает и участников, и заявки, и челленджи."""
        self.grant("clubs", LEVEL_EDIT)
        perms = self._perms()
        for model in ("club", "clubmember", "clubjoinrequest", "clubchallenge"):
            self.assertIn(f"clubs.change_{model}", perms)

    def test_changelist_of_foreign_model_is_denied(self):
        self.grant("catalog.products", LEVEL_FULL)
        self.login_staff()
        self.assertEqual(self.client.get("/admin/catalog/product/").status_code, 200)
        self.assertEqual(self.client.get("/admin/orders/order/").status_code, 403)


class OwnerOnlyTests(Base):
    """Вкладка «Сотрудники» — только владельцу, и не через меню, а на сервере."""

    def test_staff_cannot_open_the_tab(self):
        self.login_staff()
        for url in ("/admin/staff/", f"/admin/staff/{self.profile.pk}/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_staff_cannot_grant_rights_to_himself(self):
        """Главная попытка обхода: сотрудник сам себе выдаёт вкладку."""
        self.login_staff()
        r = self.client.post(f"/admin/staff/{self.profile.pk}/rights",
                             {"tab__onec_log": LEVEL_FULL})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TabPermission.objects.filter(user=self.staff).exists())

    def test_staff_cannot_touch_another_profile_by_id(self):
        """Подстановка чужого id ничего не даёт: право проверяется по сессии."""
        other = User.objects.create_user("other@t.dev", "other@t.dev", "x", is_staff=True)
        other_profile = StaffProfile.objects.create(user=other, full_name="Другой")
        self.login_staff()
        r = self.client.post(f"/admin/staff/{other_profile.pk}/action", {"action": "toggle"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(User.objects.get(pk=other.pk).is_active)

    def test_second_superuser_simply_cannot_exist(self):
        """С S-13 второго владельца не бывает: флаг снимается при сохранении."""
        boss = User.objects.create_superuser("boss", "b@t.dev", "x")
        self.assertFalse(User.objects.get(pk=boss.pk).is_superuser)

    def test_superuser_record_is_not_managed_from_the_tab(self):
        """Если флаг всё же оказался в базе (прямым запросом), вкладка его не трогает."""
        boss = User.objects.create_user("boss@t.dev", "boss@t.dev", "x", is_staff=True)
        boss_profile = StaffProfile.objects.create(user=boss, full_name="Второй владелец")
        User.objects.filter(pk=boss.pk).update(is_superuser=True)   # мимо сигнала
        self.login_owner()
        self.assertEqual(self.client.get(f"/admin/staff/{boss_profile.pk}/").status_code, 403)

    def test_owner_sees_the_tab(self):
        self.login_owner()
        r = self.client.get("/admin/staff/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Иван Петров")

    def test_anonymous_is_redirected_to_login(self):
        r = self.client.get("/admin/staff/")
        self.assertIn(r.status_code, (302, 403))


class RightsFormTests(Base):
    def setUp(self):
        super().setUp()
        self.login_owner()

    def test_owner_sets_and_clears_rights(self):
        self.client.post(f"/admin/staff/{self.profile.pk}/rights",
                         {"tab__orders": LEVEL_EDIT, "tab__onec_log": LEVEL_VIEW})
        self.assertEqual(TabPermission.objects.get(user=self.staff, tab="orders").level, LEVEL_EDIT)
        # Пустая форма = всё снято: отсутствие записи и есть отказ.
        self.client.post(f"/admin/staff/{self.profile.pk}/rights", {})
        self.assertFalse(TabPermission.objects.filter(user=self.staff).exists())

    def test_unknown_level_falls_back_to_none(self):
        """Подмена значения в форме не даёт выдумать себе уровень."""
        self.client.post(f"/admin/staff/{self.profile.pk}/rights",
                         {"tab__orders": "superadmin"})
        self.assertFalse(TabPermission.objects.filter(user=self.staff, tab="orders").exists())

    def test_unknown_tab_is_ignored(self):
        self.client.post(f"/admin/staff/{self.profile.pk}/rights",
                         {"tab__auth.user": LEVEL_FULL})
        self.assertFalse(TabPermission.objects.filter(tab="auth.user").exists())

    def test_change_is_written_to_audit(self):
        self.client.post(f"/admin/staff/{self.profile.pk}/rights", {"tab__orders": LEVEL_EDIT})
        entry = StaffAudit.objects.filter(target=self.staff).first()
        self.assertIsNotNone(entry)
        self.assertIn("Заказы", entry.action)


class InviteTests(Base):
    def test_owner_creates_staff_and_gets_link(self):
        self.login_owner()
        r = self.client.post("/admin/staff/create", {
            "full_name": "Пётр Сидоров", "email": "petr@mata-club.ru"}, follow=True)
        self.assertEqual(r.status_code, 200)
        user = User.objects.get(username="petr@mata-club.ru")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())   # до приглашения войти нельзя
        self.assertContains(r, "/admin/invite/")

    def test_accepting_invite_sets_password_once(self):
        token = self.profile.issue_invite()
        r = self.client.post(f"/admin/invite/{token}/",
                             {"password1": "Sprint-2026-run", "password2": "Sprint-2026-run"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.get(pk=self.staff.pk).check_password("Sprint-2026-run"))
        # Повторно та же ссылка не работает.
        self.assertEqual(self.client.get(f"/admin/invite/{token}/").status_code, 404)

    def test_expired_invite_is_refused(self):
        token = self.profile.issue_invite()
        self.profile.invite_expires = timezone.now() - timedelta(minutes=1)
        self.profile.save(update_fields=["invite_expires"])
        self.assertEqual(self.client.get(f"/admin/invite/{token}/").status_code, 404)

    def test_wrong_token_is_refused(self):
        self.profile.issue_invite()
        self.assertEqual(self.client.get("/admin/invite/подобранный-токен/").status_code, 404)

    def test_token_is_not_stored_in_plain(self):
        token = self.profile.issue_invite()
        self.profile.refresh_from_db()
        self.assertNotEqual(self.profile.invite_hash, token)
        self.assertNotIn(token, self.profile.invite_hash)

    def test_weak_passwords_are_refused(self):
        """Короткий, только цифры и словарный — каждый отбивается своим правилом."""
        for weak in ("Short-1a", "12345678901", "password123"):
            token = self.profile.issue_invite()
            r = self.client.post(f"/admin/invite/{token}/",
                                 {"password1": weak, "password2": weak})
            self.assertEqual(r.status_code, 200, weak)
            self.assertFalse(User.objects.get(pk=self.staff.pk).check_password(weak), weak)

    def test_mismatched_passwords_are_refused(self):
        token = self.profile.issue_invite()
        self.client.post(f"/admin/invite/{token}/",
                         {"password1": "Sprint-2026-run", "password2": "Sprint-2026-RUN"})
        self.assertFalse(User.objects.get(pk=self.staff.pk).check_password("Sprint-2026-run"))

    def test_bruteforce_is_throttled(self):
        for _ in range(21):
            self.client.get("/admin/invite/nope/")
        self.assertEqual(self.client.get("/admin/invite/nope/").status_code, 429)

    def test_invite_to_disabled_staff_is_refused(self):
        token = self.profile.issue_invite()
        self.staff.is_active = False
        self.staff.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(f"/admin/invite/{token}/").status_code, 404)


class OnboardingTests(Base):
    """Второй фактор для сотрудников обязателен, для владельца — как было."""

    def test_staff_without_device_goes_to_setup(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.filter(user=self.staff).delete()
        self.grant("onec_log", LEVEL_VIEW)
        self.login_staff()
        r = self.client.get("/admin/1c-log/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/admin/2fa/setup/")

    def test_owner_is_forced_too(self):
        """Владелец без второго фактора идёт на привязку, а не в админку (D-68).

        Раньше здесь проверялось обратное — что владельца не принуждают. Именно
        поэтому на проде второй фактор оказался у сотрудника и не оказался
        у владельца: самая ценная учётная запись держалась на одном пароле.
        """
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.filter(user=self.owner).delete()
        self.login_owner()
        r = self.client.get("/admin/1c-log/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/admin/2fa/setup/")

    def test_owner_with_device_works_normally(self):
        """Привязал — и дальше всё как обычно, без лишних шагов."""
        self.login_owner()
        self.assertEqual(self.client.get("/admin/1c-log/").status_code, 200)

    def test_staff_without_tabs_lands_on_stub_not_dashboard(self):
        self.login_staff()
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/admin/no-access/")

    def test_staff_without_dashboard_lands_on_first_tab(self):
        self.grant("onec_log", LEVEL_VIEW)
        self.login_staff()
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/admin/1c-log/")

    def test_setup_page_binds_device_to_self_only(self):
        """Страница привязки не принимает чужой идентификатор ни в каком виде."""
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.filter(user=self.staff).delete()
        self.login_staff()
        self.client.get("/admin/2fa/setup/")
        self.client.post("/admin/2fa/setup/", {"code": "000000", "user": self.owner.pk})
        self.assertFalse(TOTPDevice.objects.filter(user=self.owner, confirmed=False).exists())
        self.assertTrue(TOTPDevice.objects.filter(user=self.staff).exists())


class InviteSessionTests(Base):
    """Приглашение не должно оставлять чужую сессию — иначе «права не работают».

    Реальный случай: владелец принял приглашение в своём окне, нажал «войти» и
    попал в админку под собой (Django пускает уже вошедшего мимо формы). Выглядит
    как полный доступ у сотрудника, хотя сотрудник не входил ни разу.
    """

    def test_owner_session_is_closed_after_accepting(self):
        self.login_owner()
        token = self.profile.issue_invite()
        r = self.client.post(f"/admin/invite/{token}/",
                             {"password1": "Kvartal-Osen-2026", "password2": "Kvartal-Osen-2026"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "мы из неё вышли")
        # Сессия владельца закрыта: страница входа теперь покажет форму, а не админку.
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_open_invite_warns_about_current_session(self):
        self.login_owner()
        token = self.profile.issue_invite()
        r = self.client.get(f"/admin/invite/{token}/")
        self.assertContains(r, "открыта админка под")

    def test_anonymous_accept_needs_no_warning(self):
        token = self.profile.issue_invite()
        r = self.client.post(f"/admin/invite/{token}/",
                             {"password1": "Kvartal-Osen-2026", "password2": "Kvartal-Osen-2026"})
        self.assertNotContains(r, "мы из неё вышли")

    def test_member_card_lists_what_he_sees(self):
        self.grant("orders", LEVEL_EDIT)
        self.grant("onec_log", LEVEL_VIEW)
        self.login_owner()
        r = self.client.get(f"/admin/staff/{self.profile.pk}/")
        self.assertContains(r, "Что ему видно")
        self.assertContains(r, "Заказы")
        self.assertContains(r, "Журнал обмена")
        self.assertEqual(len(r.context["granted"]), 2)


class SidebarTabRegistryTests(TestCase):
    """Страж S-12: каждая вкладка меню, раздаваемая по праву (`_tab`), обязана быть
    в реестре `TABS` — иначе новую вкладку не выдать сотруднику (её не будет в форме
    прав). Так «вновь добавляемые вкладки» автоматически попадают в экран доступа."""

    @staticmethod
    def _sidebar_tab_keys():
        from django.conf import settings
        keys = []
        for section in settings.UNFOLD["SIDEBAR"]["navigation"]:
            for item in section.get("items", []):
                key = getattr(item.get("permission"), "_tab_key", None)
                if key:
                    keys.append(key)
        return keys

    def test_every_menu_tab_is_registered(self):
        from staff.tabs import BY_KEY
        missing = [k for k in self._sidebar_tab_keys() if k not in BY_KEY]
        self.assertEqual(missing, [], f"вкладки меню без записи в TABS: {missing}")

    def test_app_flags_tab_is_grantable(self):
        from staff.tabs import BY_KEY
        self.assertIn("app_flags", BY_KEY)
        self.assertIn("app_flags", self._sidebar_tab_keys())
