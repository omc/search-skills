---
name: bonsai-database-search
description: Design and implement a unified search index for an entire database in Elasticsearch or OpenSearch. Reads the full database schema (DDL or ORM models), discovers domain-specific information needs (identifiers, phone numbers, currencies, etc.), maps all tables into a single index with a base schema extended by domain fields, and generates index definitions, data transform code, and query templates with permissions-based access control.
triggers:
  - bonsai-database-search
  - bonsai-database-search design
  - bonsai-database-search implement
  - bonsai-database-search opensearch
  - bonsai-database-search elasticsearch
  - bonsai-database-search unified index
  - bonsai-database-search single index
  - bonsai-database-search schema
---
# bonsai-database-search

Open `@references/guide.md` and follow it. Do not proceed without it.

Design and implement a unified search index for an entire database in Elasticsearch or OpenSearch. Reads the full database schema (DDL, ORM models, or migration files), runs domain discovery to identify product-specific information needs — identifiers like SKUs and order numbers, phone numbers, currencies, tags, and more — then maps all tables into a single index built from a base schema extended with domain-specific fields and analyzers. Generates the complete index definition, per-table data transform code, and a query template with permissions-based access control. Based on battle-tested techniques from 15 years of search engineering at Bonsai.
