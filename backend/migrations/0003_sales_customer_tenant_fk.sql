alter table sales drop constraint if exists sales_customer_id_fkey;
alter table sales drop constraint if exists sales_workspace_customer_fk;
alter table sales
  add constraint sales_workspace_customer_fk
  foreign key (workspace_id, customer_id) references customers(workspace_id, id);
