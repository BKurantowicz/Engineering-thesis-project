# ERP & Warehouse Management System

## 📌 Project Overview

This application is an ERP system created to monitor incoming orders and assist with warehouse operations and implementations. It provides a comprehensive set of tools to manage inventory, process shipments, and analyze business performance.

The application is built with a focus on usability and supports bilingual interface localization (English and Polish).

## 🚀 Key Features

* **Order Management:** Add, delete, modify, and manage user orders seamlessly.

* **Invoicing:** Generate and manage invoices independently of customer profiles (supporting B2B/company details and separate billing addresses).

* **Data Import:** Built-in tools to import external orders directly into the database.

* **Warehouse Control:** Track inventory levels, product locations (shelves/racks), and pick lists.

* **Analytics & Statistics:** View detailed statistics regarding sales, top products, and overall business performance.

* **Bilingual Support:** Database architecture designed to support multiple languages natively.

## 🛠️ Technology Stack

* **Language:** Python 3

* **GUI Framework:** PySide6 (Qt for Python) - ensuring a fast, responsive, and native desktop experience.

* **Database:** SQLite3 - lightweight, serverless, and robust internal database.

* **Configuration:** JSON - used for local application settings, paths, and user preferences.

## 🗄️ Database Architecture

Below is the Entity-Relationship Diagram (ERD) mapping the core structure of the system. Dictionary tables (prefixed with `DICT_`) store names in both Polish (`name_pl`) and English (`name_en`) to natively support bilingual interface requirements.

```mermaid
erDiagram
    %% CORE TABLES %%
    USERS {
        int id PK
        string username
        string password_hash
        string role
    }

    CUSTOMERS {
        int id PK
        string first_name
        string last_name
        string email
        string phone
    }

    PRODUCTS {
        int id PK
        string sku
        string base_name
        float default_price
    }

    %% WAREHOUSE MODULE %%
    WAREHOUSE_SHELVES {
        int id PK
        string shelf_code "e.g., A1-01"
    }

    INVENTORY {
        int id PK
        int product_id FK
        int shelf_id FK
        int quantity
    }

    %% ORDER & INVOICE MODULE %%
    ORDERS {
        int id PK
        int customer_id FK
        int status_id FK
        int payment_method_id FK
        int shipping_type_id FK
        datetime created_at
        float total_amount
    }

    ORDER_ITEMS {
        int id PK
        int order_id FK
        int product_id FK
        int quantity
        float unit_price
    }

    INVOICES {
        int id PK
        int order_id FK
        string invoice_number
        string buyer_name "Person or Company Name"
        string tax_id "NIP (optional)"
        string address
        datetime issue_date
    }

    %% DICTIONARY TABLES (BILINGUAL SUPPORT) %%
    DICT_ORDER_STATUSES {
        int id PK
        string name_pl "e.g., Nowe"
        string name_en "e.g., New"
    }

    DICT_SHIPPING_TYPES {
        int id PK
        string name_pl "e.g., Kurier"
        string name_en "e.g., Courier"
    }

    DICT_PAYMENT_METHODS {
        int id PK
        string name_pl "e.g., Przelew"
        string name_en "e.g., Bank Transfer"
    }

    %% RELATIONSHIPS %%
    CUSTOMERS ||--o{ ORDERS : "places"
    DICT_ORDER_STATUSES ||--o{ ORDERS : "defines status of"
    DICT_SHIPPING_TYPES ||--o{ ORDERS : "defines shipping for"
    DICT_PAYMENT_METHODS ||--o{ ORDERS : "defines payment for"
    
    ORDERS ||--|{ ORDER_ITEMS : "contains"
    ORDERS ||--o| INVOICES : "generates"
    
    PRODUCTS ||--o{ ORDER_ITEMS : "is part of"
    PRODUCTS ||--o{ INVENTORY : "has stock in"
    
    WAREHOUSE_SHELVES ||--o{ INVENTORY : "stores"

```

### Database Architecture Notes:

* **Separation of Invoices:** The `INVOICES` table allows billing details (like company name and tax ID) to differ from the original `CUSTOMERS` record, supporting both B2C and B2B transactions.
* **Dictionary Tables (`DICT_`):** These enable seamless switching between languages in the PySide6 UI without hardcoding translations in the backend logic.
* **Granular Inventory:** The `INVENTORY` table acts as a junction, tracking exactly how many units of a specific product are located on a specific warehouse shelf.
