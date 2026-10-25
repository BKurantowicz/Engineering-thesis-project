# ERP & Warehouse Management System

## 📌 Project Overview

This application is an ERP system created to monitor incoming orders and assist with warehouse operations and implementations. It provides a comprehensive set of tools to manage inventory, process shipments, and analyze business performance.

The application is built with a focus on usability and supports bilingual interface localization (English and Polish).

## 🚀 Key Features

- **Order Management:** Add, delete, modify, and manage user orders seamlessly.

- **Invoicing:** Generate and manage invoices independently of customer profiles (supporting B2B/company details and separate billing addresses).

- **Data Import:** Built-in tools to import external orders directly into the database.

- **Warehouse Control:** Track inventory levels, product locations (shelves/racks), and pick lists.

- **Analytics & Statistics:** View detailed statistics regarding sales, top products, and overall business performance.

- **Bilingual Support:** Database architecture designed to support multiple languages natively.

- **Dynamic Configuration & Theming:** Centralized settings module managing system paths, company metadata, and localization. Features a live CSS `ThemeManager` for zero-restart visual switching (Dark, Light, Modern) and scalable UI fonts safely persisted in a recursive JSON structure.

## 🛠️ Technology Stack

- **Language:** Python 3

- **GUI Framework:** PySide6 (Qt for Python) - ensuring a fast, responsive, and native desktop experience.

- **Database:** SQLite3 - lightweight, serverless, and robust internal database.

- **Configuration:** JSON - used for local application settings, paths, and user preferences.

## Running from a Checkout

Install Python 3 and PySide6, then run from the repository root:

```text
python -m pip install PySide6
python main.py
```

The database module is tracked as `models/database.py` and imported as
`models.database`. Keep this lowercase package spelling when adding imports;
startup does not require directory renaming or Python case-handling overrides.
Database initialization creates missing tables and leaves existing business
records intact.

## Browsing Existing Orders

The Orders overview consumes the controller's named SQLite fields, including
the current delivery-address columns. Empty and populated order tables can be
opened, and missing payment or shipment details retain the `-` display default.
Expanding a row shows that order's item details. Existing date and result-limit
controls reload the list without accumulating duplicate entries.

Browsing, reloading, and expanding orders do not modify order or inventory data.

## Company Settings

In **Settings > Company Data**, the company address is edited in separate
**Street**, **Postal Code**, and **City** fields. These map directly to the existing
`company_info.street`, `company_info.postal_code`, and `company_info.city` JSON
keys. Saving and reopening settings preserves each component independently.
The labels are available in English and Polish, within the existing four-page
Settings layout.

If an older configuration contains duplicated address text, correct the affected
field explicitly and save. Existing text is displayed as stored; the application
does not guess which parts to remove. No configuration migration is required.

### Regression Tests

With Python 3, PySide6, and Git installed, run from the repository root:

```text
python -B -m unittest discover -s tests -v
```

The tests use temporary configuration and database files and Qt's offscreen
platform. They do not open the application's database or modify its configuration.
Startup coverage checks Git-tracked import capitalization, launches the entry
point from a temporary tree with the exact tracked source paths and an empty
database, and verifies that database reinitialization preserves existing records.
The startup fixture uses the default database filename; consistent custom
database-path propagation remains a separate pending repair.

Order integration tests exercise the real controller with empty and populated
databases, optional joined data, date/limit reloads, item expansion and MainWindow
startup. They verify that browsing preserves persisted records.

Settings coverage includes repeated save/reopen cycles, individual component
edits, explicit correction of existing text, and address fields in both languages
and all three themes and font sizes. Change history is recorded in
[updates.md](updates.md).

## 📸 UI Preview / Screenshots

- **Orders Dashboard:** `![Orders View](link_to_image.png)`
- **Dark Theme Interface:** `![Dark Theme](link_to_image.png)`

📦 WMS-Project <br>
 ┣ 📂 controllers        # Business logic managers (Orders, Dashboard, Settings) <br>
 ┣ 📂 models             # SQLite database manager and models <br>
 ┣ 📂 utils              # Helpers (e.g., i18n JSON Translator, ThemeManager) <br>
 ┃ ┣ 📜 translations_*.json # Feature-based language dictionaries <br>
 ┃ ┣ 📜 translations.py  # Handles dynamic glob-based multi-language translation loading <br>
 ┃ ┗ 📜 theme_manager.py # Generates and injects global QSS stylesheets dynamically <br>
 ┣ 📂 views              # PySide6 UI views (Dashboard, Orders, Products, Settings) <br>
 ┣ 📜 main.py            # Main application router and window <br>
 ┣ 📜 seed_db.py         # Faker script for generating test data <br>
 ┗ 📜 config.json        # Local app configuration, safe fallbacks, and user preferences

## 🏛️ System Architecture (UML Class Diagram)

The application utilizes a strictly typed, component-based MVC architecture. Below is the UML representation of the core application flow, highlighting the decoupling of PySide6 Views from SQLite Business Logic. 
`MainWindow` acts as the central router, instantiating and holding the sub-views.

```mermaid
classDiagram
    direction TB

    %% --- ENTRY POINT & ROUTER ---
    class MainApp {
        -config: dict
        -lang_code: string
        +main() int
    }

    class MainWindow {
        -view_orders: OrdersView
        -view_dashboard: DashboardView
        -view_settings: SettingsView
        -translator: translator
        +setup_content_area() void
        +change_view(view_name: string) void
    }

    %% --- UTILITIES ---
    class translator {
        -lang_code: string
        -translations: dict
        +load_all_translations(directory: string) void
        +t(key: string, fallback: string) string
    }

    class ThemeManager {
        <<static>>
        +get_stylesheet(theme_name: string, font_size_name: string) string
    }

    %% --- VIEWS (UI Layer) ---
    class DashboardView {
        -controller: DashboardController
        -trend_chart: QChart
        -capacity_chart: QChart
        -status_chart: QChart
        +setup_ui() void
        +load_real_data() void
        +update_trend_chart(filter_type: string) void
    }

    class OrdersView {
        -controller: OrderController
        -scroll_layout: QVBoxLayout
        +load_orders() void
        +filter_orders_in_memory() void
    }

    class SettingsView {
        -controller: SettingsController
        +setup_ui() void
        +load_settings() void
        +save_settings() void
    }

    class OrderAccordionItem {
        -order_id_str: string
        -summary_row: ClickableRow
        -details_panel: QFrame
        +__init__(order_data, translator, controller)
    }

    class ClickableRow {
        -is_expanded: bool
        -details_panel: QFrame
        +set_details_panel(panel: QFrame) void
        +mousePressEvent(event: QEvent) void
    }

    %% --- CONTROLLERS (Business Logic Layer) ---
    class DashboardController {
        -db_path: string
        +get_order_status_counts() dict
        +get_warehouse_capacity() dict
        +get_order_trend(filter_type: string) dict
    }

    class OrderController {
        -db_path: string
        +get_orders(limit: int, date_filter: string) list
        +get_order_items(order_id: int) list
    }

    class SettingsController {
        -config_path: string
        -default_config: dict
        +get_config() dict
        +save_config(new_config: dict) bool
        -_merge_configs(default: dict, current: dict) dict
    }

    %% --- DATABASE ---
    class DatabaseManager {
        -db_path: string
        +initialize_database() void
        +get_connection() Connection
    }

    %% ==========================================
    %% RELATIONSHIPS & ROUTING (Strictly Ordered)
    %% ==========================================

    %% 1. Application Init
    MainApp --> MainWindow : instantiates
    MainApp ..> DatabaseManager : configures path
    MainApp ..> ThemeManager : loads initial CSS

    %% 2. Global Aggregations
    MainWindow o-- translator : holds & injects into views

    %% 3. View Compositions (MainWindow owns the Views)
    MainWindow *-- DashboardView
    MainWindow *-- OrdersView
    MainWindow *-- SettingsView
    
    %% 4. View Sub-components
    OrdersView *-- OrderAccordionItem
    OrderAccordionItem *-- ClickableRow

    %% 5. View to Controller Links
    DashboardView o-- DashboardController
    OrdersView o-- OrderController
    SettingsView o-- SettingsController

    %% 6. Controller to Database Links
    DashboardController ..> DatabaseManager : queries
    OrderController ..> DatabaseManager : queries

    %% 7. Local Triggers
    SettingsView ..> ThemeManager : updates CSS on save
```

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
        int user_id PK
        string username
        string password_hash
        string first_name
        string last_name
        string role
    }
    CUSTOMERS {
        int customer_id PK
        string first_name
        string last_name
        string email
        string street
        string postal_code
        string city
        datetime created_at
    }
    PRODUCTS {
        int product_id PK
        string sku
        string name_pl
        string name_en
        string desc_pl
        string desc_en
        float price
        float weight
        float length
        float width
        float height
    }

    %% WAREHOUSE MODULE %%
    LOCATIONS {
        int location_id PK
        string location_code "e.g., A1-01"
        float max_weight
        float max_volume
    }
    INVENTORY {
        int product_id PK, FK
        int location_id PK, FK
        int quantity
    }
    INVENTORY_TRANSACTIONS {
        int transaction_id PK
        int product_id FK
        int location_id FK
        int user_id FK
        int quantity_change "e.g., -2 or +10"
        string transaction_type "e.g., PICK, RESTOCK"
        datetime created_at
    }
    PICK_LISTS {
        int pick_list_id PK
        string status "e.g., PENDING"
        int assigned_user_id FK
        datetime created_at
    }
    PICK_LIST_ORDERS {
        int pick_list_id PK, FK
        int order_id PK, FK
    }

    %% ORDER & INVOICE MODULE %%
    ORDERS {
        int order_id PK
        int customer_id FK
        string status_code FK
        int payment_method_id FK
        int created_by FK
        datetime order_date
        float total_amount
        string delivery_name
        string delivery_second_name
        string delivery_street
        string delivery_postal_code
        string delivery_city
    }
    ORDER_ITEMS {
        int item_id PK
        int order_id FK
        int product_id FK
        int quantity
        float unit_price
    }
    ORDER_SHIPMENTS {
        int shipment_id PK
        int order_id FK
        int shipping_type_id FK
        string package_code FK
        string tracking_number
        float final_shipping_cost
    }
    INVOICES {
        int invoice_id PK
        int order_id FK
        string invoice_number
        string company_name
        string tax_id
        string billing_name
        string billing_second_name
        string billing_street
        string billing_postal_code
        string billing_city
        datetime issue_date
    }

    %% DICTIONARY TABLES (BILINGUAL SUPPORT) %%
    DICT_ORDER_STATUSES {
        string status_code PK
        string name_pl "e.g., Nowe"
        string name_en "e.g., New"
    }
    DICT_SHIPPING_METHODS {
        int shipping_id PK
        string carrier_name "e.g., InPost"
        string service_name_pl "e.g., Paczkomat"
        string service_name_en "e.g., Parcel Locker"
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
        float max_length
        float max_width
        float max_height
        float base_cost
    }

    %% --- RELATIONSHIPS --- %%

    %% 1. Core Order Flow
    CUSTOMERS ||--o{ ORDERS : "places"
    ORDERS ||--|{ ORDER_ITEMS : "contains"
    PRODUCTS ||--o{ ORDER_ITEMS : "is part of"
    
    %% 2. Order Fulfillment & Finance
    ORDERS ||--o| INVOICES : "generates"
    ORDERS ||--o| ORDER_SHIPMENTS : "shipped via"
    ORDERS ||--o{ PICK_LIST_ORDERS : "assigned to"
    PICK_LISTS ||--|{ PICK_LIST_ORDERS : "contains"
    
    %% 3. Inventory & Warehouse
    PRODUCTS ||--o{ INVENTORY : "has stock in"
    LOCATIONS ||--o{ INVENTORY : "stores"
    PRODUCTS ||--o{ INVENTORY_TRANSACTIONS : "involved in"
    LOCATIONS ||--o{ INVENTORY_TRANSACTIONS : "location of"
    
    %% 4. User Actions
    USERS ||--o{ INVENTORY_TRANSACTIONS : "performs"
    USERS ||--o{ PICK_LISTS : "assigned to"
    USERS ||--o{ ORDERS : "created by"

    %% 5. Dictionaries
    DICT_ORDER_STATUSES ||--o{ ORDERS : "defines status"
    DICT_PAYMENT_METHODS ||--o{ ORDERS : "defines payment"
    DICT_SHIPPING_METHODS ||--o{ ORDER_SHIPMENTS : "defines carrier"
    DICT_PACKAGE_TYPES ||--o{ ORDER_SHIPMENTS : "defines package size"

```

### Database Architecture Notes:

* **Separation of Invoices:** The `INVOICES` table allows billing details (like company name and tax ID) to differ from the original `CUSTOMERS` record, supporting both B2C and B2B transactions.
* **Dictionary Tables (`DICT_`):** These enable seamless switching between languages in the PySide6 UI without hardcoding translations in the backend logic.
* **Granular Inventory:** The `INVENTORY` table acts as a junction, tracking exactly how many units of a specific product are located on a specific warehouse shelf.
