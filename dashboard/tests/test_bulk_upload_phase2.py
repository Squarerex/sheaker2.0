from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from catalog.models import Inventory, Variant
from dashboard.models import ImportLog


class BulkUploadPhase2Tests(TestCase):
    def setUp(self) -> None:
        # Ensure groups used by your authz layer exist
        for name in ["admin", "editor", "marketer", "vendor"]:
            Group.objects.get_or_create(name=name)

    # ------------ helpers ------------
    def login_user_with_roles(self, username: str, roles: list[str]):
        U = get_user_model()
        u = U.objects.create_user(username, f"{username}@x.com", "x")
        # Django admin access requires is_staff True; your authz is group-based.
        u.is_staff = True
        u.is_superuser = "admin" in roles
        u.save()
        for r in roles:
            g = Group.objects.get(name=r)
            u.groups.add(g)
        self.client.login(username=username, password="x")
        return u

    def _post_upload(self, payload, *, is_json=True, update_existing=True):
        if is_json:
            content = json.dumps(payload).encode("utf-8")
            f = SimpleUploadedFile(
                "upload.json", content, content_type="application/json"
            )
        else:
            content = payload.encode("utf-8")
            f = SimpleUploadedFile("upload.csv", content, content_type="text/csv")
        resp = self.client.post(
            reverse("dashboard:product_upload"),
            {"file": f, "update_existing": "on" if update_existing else ""},
        )
        assert resp.status_code == 302
        return resp["Location"]

    def _extract_token_upsert(self, location_url: str):
        q = parse_qs(urlparse(location_url).query)
        return q.get("token", [""])[0], (q.get("upsert", ["1"])[0] == "1")

    # ------------ tests ------------
    def test_editor_preview_and_commit(self):
        self.login_user_with_roles("ed", ["editor"])

        sample = [
            {
                "title": "A",
                "sku": "S-1",
                "price": "10.00",
                "currency": "USD",
                "qty_available": 5,
                "stock_mode": "set",
            },
            {
                "title": "B",
                "sku": "S-2",
                "price": "11.50",
                "currency": "USD",
                "qty_available": 2,
                "stock_mode": "increment",
            },
        ]
        loc = self._post_upload(sample, is_json=True)

        # Preview
        r = self.client.get(loc)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Create:", r.content)

        token, _ = self._extract_token_upsert(loc)

        # Dry-run allowed
        r2 = self.client.post(
            reverse("dashboard:product_upload_commit"),
            {"token": token, "upsert": "1", "dry_run": "1"},
        )
        self.assertIn(r2.status_code, (200, 302))
        self.assertEqual(Variant.objects.count(), 0)

        # Real commit allowed for editor
        r3 = self.client.post(
            reverse("dashboard:product_upload_commit"), {"token": token, "upsert": "1"}
        )
        self.assertIn(r3.status_code, (200, 302))
        self.assertEqual(Variant.objects.count(), 2)
        self.assertEqual(Inventory.objects.count(), 2)
        self.assertGreaterEqual(ImportLog.objects.count(), 1)

    def test_marketer_dry_run_only(self):
        self.login_user_with_roles("mk", ["marketer"])
        sample = [{"title": "M", "sku": "M-1", "price": "9.99", "currency": "USD"}]
        loc = self._post_upload(sample, is_json=True)
        token, _ = self._extract_token_upsert(loc)

        # Dry-run OK
        r1 = self.client.post(
            reverse("dashboard:product_upload_commit"),
            {"token": token, "upsert": "1", "dry_run": "1"},
        )
        self.assertIn(r1.status_code, (200, 302))
        self.assertEqual(Variant.objects.count(), 0)

        # Real commit forbidden
        r2 = self.client.post(
            reverse("dashboard:product_upload_commit"), {"token": token, "upsert": "1"}
        )
        self.assertEqual(r2.status_code, 403)
        self.assertEqual(Variant.objects.count(), 0)

    def test_inventory_set_then_increment(self):
        self.login_user_with_roles("ed2", ["editor"])

        # First commit: set=5
        loc1 = self._post_upload(
            [
                {
                    "title": "X",
                    "sku": "X-1",
                    "price": "10.00",
                    "currency": "USD",
                    "qty_available": 5,
                    "stock_mode": "set",
                }
            ],
            is_json=True,
        )
        token1, _ = self._extract_token_upsert(loc1)
        self.client.post(
            reverse("dashboard:product_upload_commit"), {"token": token1, "upsert": "1"}
        )

        v = Variant.objects.get(sku="X-1")
        inv = Inventory.objects.get(variant=v)
        self.assertEqual(inv.qty_available, 5)

        # Second commit: increment by 2 -> should be 7
        loc2 = self._post_upload(
            [
                {
                    "title": "X",
                    "sku": "X-1",
                    "price": "10.00",
                    "currency": "USD",
                    "qty_available": 2,
                    "stock_mode": "increment",
                }
            ],
            is_json=True,
        )
        token2, _ = self._extract_token_upsert(loc2)
        self.client.post(
            reverse("dashboard:product_upload_commit"), {"token": token2, "upsert": "1"}
        )
        inv.refresh_from_db()
        self.assertEqual(inv.qty_available, 7)

    def test_pagination(self):
        self.login_user_with_roles("admin1", ["admin"])
        big = [
            {"title": f"P{i}", "sku": f"SKU{i}", "price": "9.99"} for i in range(1200)
        ]
        loc = self._post_upload(big, is_json=True)
        r = self.client.get(loc + "&page=3&per=500")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"of 3 pages", r.content)

    def test_mapping_and_currency_validation_and_errors_json(self):
        self.login_user_with_roles("admin2", ["admin"])
        csv_text = "title,SKU,price,currency\nX,MX-1,12.00,ZZZ\n"
        # Upload CSV
        content = csv_text.encode("utf-8")
        f = SimpleUploadedFile("upload.csv", content, content_type="text/csv")
        resp = self.client.post(
            reverse("dashboard:product_upload"), {"file": f, "update_existing": "on"}
        )
        self.assertEqual(resp.status_code, 302)
        loc = resp["Location"]
        token, _ = self._extract_token_upsert(loc)

        # Apply mapping: SKU -> sku
        r = self.client.post(
            reverse("dashboard:product_upload_preview"),
            {
                "token": token,
                "upsert": "1",
                "apply_mapping": "1",
                "mapping[sku]": "SKU",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"must be one of", r.content)  # shows allowed currency options

        # Errors JSON
        r2 = self.client.get(
            reverse("dashboard:product_upload_errors_json") + f"?token={token}&upsert=1"
        )
        self.assertEqual(r2.status_code, 200)
        data = r2.json()
        self.assertTrue("errors" in data and len(data["errors"]) >= 1)

    def test_samples_available(self):
        self.login_user_with_roles("ed3", ["editor"])
        rj = self.client.get(reverse("dashboard:product_upload_sample_json"))
        rc = self.client.get(reverse("dashboard:product_upload_sample_csv"))
        self.assertEqual(rj.status_code, 200)
        self.assertEqual(rc.status_code, 200)
