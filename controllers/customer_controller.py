"""Customer master-data access and validation, independent of historical orders."""

from contextlib import closing
from email.errors import HeaderParseError
from email.headerregistry import Address
import re
import sqlite3


class CustomerValidationError(ValueError):
    def __init__(self, code, field=None):
        super().__init__(code)
        self.code = code
        self.field = field


class CustomerController:
    FIELDS = ("first_name", "last_name", "street", "postal_code", "city", "email", "phone")
    REQUIRED_FIELDS = FIELDS[:5]

    def __init__(self, db_path="warehouse.db"):
        self.db_path = db_path

    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def get_customers(self):
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT customer_id, first_name, last_name, street, postal_code, city, email, phone "
                "FROM customers ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, customer_id"
            ).fetchall()

    def get_customer(self, customer_id):
        with closing(self._connect()) as connection:
            customer = connection.execute(
                "SELECT customer_id, first_name, last_name, street, postal_code, city, email, phone "
                "FROM customers WHERE customer_id = ?", (customer_id,),
            ).fetchone()
        if customer is None:
            raise CustomerValidationError("not_found")
        return customer

    @staticmethod
    def _email_key(email):
        return (email or "").strip().casefold()

    def get_email_conflicts(self):
        """Report legacy collisions without merging, deleting, or rewriting rows."""
        groups = {}
        with closing(self._connect()) as connection:
            for row in connection.execute("SELECT customer_id, email FROM customers ORDER BY customer_id"):
                key = self._email_key(row["email"])
                if key:
                    groups.setdefault(key, []).append(row["customer_id"])
        return [ids for ids in groups.values() if len(ids) > 1]

    def save_customer(self, data, customer_id=None):
        values = self.validate(data)
        with closing(self._connect()) as connection, connection:
            # Serialize the uniqueness check and write, including separate app instances.
            connection.execute("BEGIN IMMEDIATE")
            if customer_id is not None and connection.execute(
                "SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,),
            ).fetchone() is None:
                raise CustomerValidationError("not_found")
            email_key = self._email_key(values["email"])
            if email_key:
                for row in connection.execute("SELECT customer_id, email FROM customers WHERE email IS NOT NULL"):
                    if row["customer_id"] != customer_id and self._email_key(row["email"]) == email_key:
                        raise CustomerValidationError("duplicate_email", "email")
            parameters = tuple(values[field] for field in self.FIELDS)
            if customer_id is None:
                cursor = connection.execute(
                    "INSERT INTO customers (first_name, last_name, street, postal_code, city, email, phone) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", parameters,
                )
                customer_id = cursor.lastrowid
            else:
                connection.execute(
                    "UPDATE customers SET first_name = ?, last_name = ?, street = ?, postal_code = ?, "
                    "city = ?, email = ?, phone = ? WHERE customer_id = ?", parameters + (customer_id,),
                )
        return customer_id

    @classmethod
    def validate(cls, data):
        values = {}
        for field in cls.FIELDS:
            value = data.get(field, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise CustomerValidationError("invalid_value", field)
            values[field] = value.strip()
            if field in cls.REQUIRED_FIELDS and not values[field]:
                raise CustomerValidationError("required", field)
        if values["email"]:
            try:
                address = Address(addr_spec=values["email"])
                domain = address.domain.encode("idna").decode("ascii")
                labels = domain.split(".")
                if not address.username or not domain or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                    for label in labels
                ):
                    raise ValueError("Invalid email structure")
            except (ValueError, HeaderParseError, UnicodeError):
                raise CustomerValidationError("invalid_email", "email") from None
        for field in ("email", "phone"):
            values[field] = values[field] or None
        return values
