SELECT c.name, SUM(o.amount) as total
FROM orders o
JOIN customers c ON o.customer_id = c.id
GROUP BY c.name
ORDER BY total DESC
