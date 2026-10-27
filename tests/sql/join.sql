create table users (id integer not null, name text not null);
create table tasks (uid integer not null, task text not null);
insert into users (id, name) values (1, 'alice');
insert into users (id, name) values (2, 'bob');
insert into tasks (uid, task) values (1, 'write');
insert into tasks (uid, task) values (2, 'review');
insert into tasks (uid, task) values (2, 'test');
select u.name, t.task from users u, tasks t where u.id = t.uid;
create branch b1 from master;
insert into tasks version b1 (uid, task) values (1, 'deploy');
select u.name, t.task from users version b1 u, tasks version b1 t where u.id = t.uid;
select u.name, t.task from users u, tasks t where u.id = t.uid;
quit
