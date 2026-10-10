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

## 📸 UI Preview / Screenshots

* **Orders Dashboard:** `![Orders View](link_to_image.png)`
* **Dark Theme Interface:** `![Dark Theme](link_to_image.png)`

📦 WMS-Project
 ┣ 📂 models             # SQLite database manager and models <br>
 ┣ 📂 utils              # Helpers (e.g., i18n JSON Translator) <br>
 ┣ 📂 views              # PySide6 UI views (Dashboard, Orders, Products) <br>
 ┣ 📜 main.py            # Main application router and window <br>
 ┣ 📜 seed_db.py         # Faker script for generating test data <br>
 ┣ 📜 config.json        # Local app configuration and styling paths <br>
 ┗ 📜 translations_*.json # Feature-based language dictionaries

## 🏛️ System Architecture (UML Class Diagram)

The application utilizes a strictly typed, component-based MVC architecture. Below is the UML representation of the core application flow, highlighting the decoupling of PySide6 Views from SQLite Business Logic.

![MVC.jpg](Images/MVC.jpg)

### Architecture Notes:
- **Separation of Concerns:** UI classes (`OrdersView`, `OrderAccordionItem`) never execute SQL. They delegate all data retrieval to the `OrderController`.
- **Dynamic Instantiation:** `OrdersView` acts as a factory, generating multiple `OrderAccordionItem` instances based on the tuple list returned by the controller.
- **Composition (*--) vs Aggregation (o--):** The diagram strictly differentiates between widgets that physically own other widgets (if you delete the View, the Accordions are destroyed) versus references to shared utilities like the `translator` or `OrderController`.

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
    INVENTORY_TRANSACTIONS {
        int id PK
        int product_id FK
        int shelf_id FK
        int user_id FK
        int quantity_change "e.g., -2 or +10"
        string transaction_type "e.g., PICK, RESTOCK"
        datetime created_at
    }
    PICK_LISTS {
        int id PK
        string status "e.g., PENDING, PICKING"
        int assigned_user_id FK
        datetime created_at
    }
    PICK_LIST_ORDERS {
        int pick_list_id PK, FK
        int order_id PK, FK
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
    ORDER_SHIPMENTS {
        int id PK
        int order_id FK
        int shipping_type_id FK
        string package_code
        string tracking_number
        float final_shipping_cost
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
    DICT_PACKAGE_TYPES {
        string package_code PK
        string name_pl
        string name_en
        float max_weight
        float base_cost
    }

    %% --- RELATIONSHIPS (Reordered for better DAG layout) --- %%

    %% 1. Core Order Flow (Center)
    CUSTOMERS ||--o{ ORDERS : "places"
    ORDERS ||--|{ ORDER_ITEMS : "contains"
    PRODUCTS ||--o{ ORDER_ITEMS : "is part of"
    
    %% 2. Order Fulfillment & Finance (Bottom/Right)
    ORDERS ||--o| INVOICES : "generates"
    ORDERS ||--o| ORDER_SHIPMENTS : "shipped via"
    ORDERS ||--o{ PICK_LIST_ORDERS : "assigned to"
    PICK_LISTS ||--|{ PICK_LIST_ORDERS : "contains"
    
    %% 3. Inventory & Warehouse (Left/Top)
    PRODUCTS ||--o{ INVENTORY : "has stock in"
    WAREHOUSE_SHELVES ||--o{ INVENTORY : "stores"
    PRODUCTS ||--o{ INVENTORY_TRANSACTIONS : "involved in"
    WAREHOUSE_SHELVES ||--o{ INVENTORY_TRANSACTIONS : "location of"
    
    %% 4. User Actions (Top)
    USERS ||--o{ INVENTORY_TRANSACTIONS : "performs"
    USERS ||--o{ PICK_LISTS : "assigned to"

    %% 5. Dictionaries (Pushed to the edges)
    ORDERS }o--|| DICT_ORDER_STATUSES : "has status"
    ORDERS }o--|| DICT_SHIPPING_TYPES : "uses shipping"
    ORDERS }o--|| DICT_PAYMENT_METHODS : "uses payment"
    ORDER_SHIPMENTS }o--|| DICT_SHIPPING_TYPES : "uses service"
    ORDER_SHIPMENTS }o--|| DICT_PACKAGE_TYPES : "uses package"

```

### Database Architecture Notes:

* **Separation of Invoices:** The `INVOICES` table allows billing details (like company name and tax ID) to differ from the original `CUSTOMERS` record, supporting both B2C and B2B transactions.
* **Dictionary Tables (`DICT_`):** These enable seamless switching between languages in the PySide6 UI without hardcoding translations in the backend logic.
* **Granular Inventory:** The `INVENTORY` table acts as a junction, tracking exactly how many units of a specific product are located on a specific warehouse shelf.
