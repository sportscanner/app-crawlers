### Geographic coordinates based filtering:

Create a new column that stores coordinates as Geometric points
```
ALTER TABLE sportsvenue
ADD COLUMN srid geometry(Point, 4326);
```

Update and populate the column whenever you add venues, or change locations
```
UPDATE sportsvenue
SET srid = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326);
```