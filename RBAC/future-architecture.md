# Future RBAC Architecture: Kessel Integration

## Overview

This document outlines the future architecture that integrates Kessel, a MariaDB-based access control API, with the existing ClusterPermissions CRD system. This integration provides enhanced performance, scalability, and advanced access control capabilities while maintaining backward compatibility.

## Architecture Components

### 1. Kessel Access Control API

**Technology Stack:**
- **Database:** MariaDB with optimized schema for access control
- **API Layer:** RESTful API with GraphQL support
- **Caching:** Redis for high-performance permission lookups
- **Authentication:** JWT tokens with refresh mechanisms

**Core Features:**
- High-performance permission evaluation
- Advanced role composition and inheritance
- Real-time permission synchronization
- Multi-tenant support with data isolation
- Audit logging and compliance reporting

### 2. ClusterPermissions CRD (Enhanced)

The existing ClusterPermissions CRD will be enhanced to support bidirectional synchronization with Kessel.

**Enhanced Structure:**
```yaml
apiVersion: rbac.example.com/v1
kind: ClusterPermissions
metadata:
  name: example-permissions
  annotations:
    kessel.managed: "true"
    kessel.sync-mode: "bidirectional"
spec:
  users:
    - name: user1
      roles:
        - cluster-admin
        - namespace-admin:namespace1
      kessel:
        priority: 100
        expiration: "2024-12-31T23:59:59Z"
  groups:
    - name: developers
      roles:
        - developer:namespace2
        - viewer:namespace3
      kessel:
        dynamic: true
        conditions:
          - type: "time-window"
            start: "09:00"
            end: "17:00"
  kessel:
    sync:
      mode: "bidirectional"
      interval: "30s"
      conflict-resolution: "kessel-wins"
    features:
      - dynamic-permissions
      - time-based-access
      - context-aware-rules
```

## Data Flow Architecture

### 1. Initial Synchronization (ClusterPermissions → Kessel)

```
ClusterPermissions CRD → Kessel Sync Controller → MariaDB Schema
```

**Process:**
1. Kessel Sync Controller watches ClusterPermissions resources
2. Extracts user/group/role data from CRD
3. Transforms data to Kessel's optimized schema
4. Bulk loads into MariaDB with conflict resolution
5. Updates Kessel's permission cache

**MariaDB Schema Design:**
```sql
-- Users table
CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Groups table
CREATE TABLE groups (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    group_name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Roles table
CREATE TABLE roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    role_name VARCHAR(255) NOT NULL,
    namespace VARCHAR(255),
    cluster VARCHAR(255),
    permissions JSON,
    priority INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User-Role assignments
CREATE TABLE user_roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT,
    role_id BIGINT,
    priority INT DEFAULT 0,
    expiration TIMESTAMP NULL,
    conditions JSON,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (role_id) REFERENCES roles(id),
    UNIQUE KEY unique_user_role (user_id, role_id)
);

-- Group-Role assignments
CREATE TABLE group_roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    group_id BIGINT,
    role_id BIGINT,
    priority INT DEFAULT 0,
    conditions JSON,
    FOREIGN KEY (group_id) REFERENCES groups(id),
    FOREIGN KEY (role_id) REFERENCES roles(id),
    UNIQUE KEY unique_group_role (group_id, role_id)
);
```

### 2. Bidirectional Synchronization

#### Kessel → ClusterPermissions Push Mechanisms

**Mechanism 1: Kubernetes Operator Pattern**
```
Kessel API → Kessel Operator → ClusterPermissions CRD
```

**Implementation:**
- Kessel Operator watches MariaDB for changes
- Detects permission modifications via database triggers
- Generates ClusterPermissions CRD updates
- Applies changes using Kubernetes client-go

**Mechanism 2: Database Triggers + Event Stream**
```
MariaDB Trigger → Event Stream → ClusterPermissions Controller
```

**Implementation:**
```sql
-- Trigger for user role changes
DELIMITER //
CREATE TRIGGER user_role_changed
AFTER INSERT ON user_roles
FOR EACH ROW
BEGIN
    INSERT INTO permission_events (event_type, user_id, role_id, action)
    VALUES ('USER_ROLE_ADDED', NEW.user_id, NEW.role_id, 'INSERT');
END//

CREATE TRIGGER user_role_updated
AFTER UPDATE ON user_roles
FOR EACH ROW
BEGIN
    INSERT INTO permission_events (event_type, user_id, role_id, action)
    VALUES ('USER_ROLE_UPDATED', NEW.user_id, NEW.role_id, 'UPDATE');
END//
DELIMITER ;
```

**Mechanism 3: Change Data Capture (CDC)**
```
MariaDB Binlog → CDC Processor → ClusterPermissions CRD
```

**Implementation:**
- Debezium or similar CDC tool monitors MariaDB binlog
- Captures all DML operations on permission tables
- Transforms events to ClusterPermissions format
- Applies changes via Kubernetes API

### 3. Real-time Permission Evaluation

```
User Request → Kessel API → MariaDB Query → Cached Response
```

**Performance Optimizations:**
- Redis caching for frequently accessed permissions
- Prepared statements for common queries
- Database connection pooling
- Query result caching with TTL

## Integration Points

### 1. Kessel Sync Controller

**Responsibilities:**
- Monitors ClusterPermissions CRD changes
- Synchronizes data to MariaDB
- Handles conflict resolution
- Manages data consistency

**Configuration:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kessel-sync-config
data:
  sync-interval: "30s"
  batch-size: "1000"
  conflict-resolution: "kessel-wins"
  retry-attempts: "3"
  mariadb:
    host: "kessel-mariadb"
    port: "3306"
    database: "access_control"
```

### 2. Kessel Operator

**Responsibilities:**
- Watches MariaDB for permission changes
- Generates ClusterPermissions CRD updates
- Manages CRD lifecycle
- Handles rollback scenarios

### 3. Enhanced Aggregate API Server

**Integration:**
- Primary permission source: Kessel API
- Fallback: Direct ClusterPermissions CRD
- Caching layer for performance
- Health checks and failover

## Advanced Features

### 1. Dynamic Permissions

**Time-based Access:**
```sql
-- Example: Office hours only access
SELECT * FROM user_roles ur
JOIN roles r ON ur.role_id = r.id
WHERE ur.user_id = ? 
  AND JSON_EXTRACT(ur.conditions, '$.time_window.start') <= CURTIME()
  AND JSON_EXTRACT(ur.conditions, '$.time_window.end') >= CURTIME();
```

**Context-aware Rules:**
```sql
-- Example: IP-based restrictions
SELECT * FROM user_roles ur
WHERE ur.user_id = ?
  AND JSON_EXTRACT(ur.conditions, '$.allowed_ips') LIKE CONCAT('%', ?, '%');
```

### 2. Permission Inheritance

**Role Hierarchy:**
```sql
-- Recursive role inheritance
WITH RECURSIVE role_hierarchy AS (
    SELECT id, role_name, parent_role_id, 1 as level
    FROM roles WHERE id = ?
    UNION ALL
    SELECT r.id, r.role_name, r.parent_role_id, rh.level + 1
    FROM roles r
    JOIN role_hierarchy rh ON r.id = rh.parent_role_id
    WHERE rh.level < 10
)
SELECT DISTINCT role_id FROM role_hierarchy;
```

### 3. Audit and Compliance

**Comprehensive Logging:**
```sql
CREATE TABLE permission_audit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT,
    action VARCHAR(50),
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    success BOOLEAN,
    details JSON
);
```

## Migration Strategy

### Phase 1: Parallel Operation
- Deploy Kessel alongside existing system
- Implement read-only synchronization (ClusterPermissions → Kessel)
- Validate data consistency

### Phase 2: Gradual Migration
- Enable bidirectional synchronization
- Migrate high-traffic workloads to Kessel
- Monitor performance and reliability

### Phase 3: Full Migration
- Kessel becomes primary permission source
- Aggregate API Server uses Kessel as primary
- ClusterPermissions CRD becomes backup/sync target

## Performance Benefits

1. **Query Performance:** MariaDB optimized queries vs. Kubernetes API calls
2. **Caching:** Redis-based permission caching
3. **Scalability:** Horizontal scaling of MariaDB cluster
4. **Concurrency:** Database-level transaction management
5. **Reduced Latency:** Direct database queries vs. API round-trips

## Security Considerations

1. **Database Security:** Encrypted connections, role-based database access
2. **API Security:** JWT authentication, rate limiting, input validation
3. **Data Privacy:** PII handling, data retention policies
4. **Audit Trail:** Comprehensive logging of all permission changes
5. **Backup and Recovery:** Automated database backups and disaster recovery

## Monitoring and Observability

### Metrics
- Permission evaluation latency
- Database query performance
- Cache hit/miss ratios
- Synchronization lag
- Error rates and types

### Alerts
- Synchronization failures
- Database connectivity issues
- High latency thresholds
- Permission conflicts
- Data consistency violations

## Conclusion

The integration of Kessel with the ClusterPermissions system provides a robust, scalable, and performant access control solution. The bidirectional synchronization ensures data consistency while the MariaDB backend delivers superior performance for permission evaluations. The architecture maintains backward compatibility while enabling advanced features like dynamic permissions and context-aware access control. 