create database if not exists WASTEWISE;
create schema if not exists WASTEWISE.RAW;
create schema if not exists WASTEWISE.ANALYTICS;
create table if not exists WASTEWISE.RAW.WASTE_EVENTS (waste_event_id varchar not null, location_id varchar not null, waste_date date not null, ingredient_id varchar not null, quantity number(18,3) not null, reason varchar not null, source_file varchar, ingested_at timestamp_ntz default current_timestamp(), primary key (waste_event_id));
create table if not exists WASTEWISE.RAW.EVENTS (event_id varchar not null, event_date date not null, event_name varchar not null, event_type varchar not null, venue varchar, expected_attendance number(18,0), attendance_quality varchar, source_url varchar, ingested_at timestamp_ntz default current_timestamp(), primary key (event_id));
create table if not exists WASTEWISE.RAW.SALES (sale_id varchar not null, location_id varchar not null, sale_date date not null, product_id varchar not null, units_sold number(18,3) not null, ingested_at timestamp_ntz default current_timestamp(), primary key (sale_id));
create table if not exists WASTEWISE.RAW.INVENTORY_SNAPSHOTS (snapshot_date date not null, location_id varchar not null, ingredient_id varchar not null, quantity_on_hand number(18,3) not null, ingested_at timestamp_ntz default current_timestamp());
