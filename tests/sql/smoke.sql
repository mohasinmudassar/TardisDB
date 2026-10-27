create table users (id integer not null, name text not null);
insert into users (id, name) values (1, 'alice');
insert into users (id, name) values (2, 'bob');
select u.id, u.name from users u;
create branch agent1 from master;
update users version agent1 set name = 'bobby' where id = 2;
insert into users version agent1 (id, name) values (3, 'carol');
select u.id, u.name from users version agent1 u;
select u.id, u.name from users u;
branch;
quit
