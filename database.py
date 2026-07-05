import aiosqlite
import json
from config import DB_PATH, DEFAULT_SETTINGS

class Database:
    def __init__(self):
        self.db = None

    async def connect(self):
        self.db = await aiosqlite.connect(DB_PATH)
        await self.db.execute("PRAGMA foreign_keys = ON")
        await self._create_tables()

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                settings TEXT,
                fed_id TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS group_users (
                group_id INTEGER,
                user_id INTEGER,
                warning_count INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                is_muted INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                captcha_tries INTEGER DEFAULT 0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                user_id INTEGER,
                admin_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                keyword TEXT,
                response TEXT
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                name TEXT,
                content TEXT,
                file_id TEXT,
                file_type TEXT
            );
            CREATE TABLE IF NOT EXISTS flood_cache (
                user_id INTEGER,
                group_id INTEGER,
                message_time REAL,
                count INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS federations (
                fed_id TEXT PRIMARY KEY,
                owner_id INTEGER,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS federation_bans (
                fed_id TEXT,
                user_id INTEGER,
                reason TEXT,
                banned_by INTEGER,
                banned_in_group INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (fed_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                creator_id INTEGER,
                title TEXT,
                description TEXT,
                event_date TEXT,
                max_participants INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS event_rsvps (
                event_id INTEGER,
                user_id INTEGER,
                status TEXT DEFAULT 'going',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                creator_id INTEGER,
                invite_link TEXT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uses INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS invite_uses (
                invite_id INTEGER,
                user_id INTEGER,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (invite_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS captcha_states (
                user_id INTEGER,
                group_id INTEGER,
                answer TEXT,
                message_id INTEGER,
                tries INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, group_id)
            );
            CREATE TABLE IF NOT EXISTS toxicity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                user_id INTEGER,
                message_text TEXT,
                score REAL,
                action_taken TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS reputation (
                group_id INTEGER,
                user_id INTEGER,
                score INTEGER DEFAULT 0,
                PRIMARY KEY (group_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                user_id INTEGER,
                content TEXT,
                send_at TIMESTAMP,
                sent INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS rules (
                group_id INTEGER PRIMARY KEY,
                content TEXT
            );
            CREATE TABLE IF NOT EXISTS shadow_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                original_ban_id INTEGER,
                reason TEXT,
                banned_by INTEGER,
                group_id INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS evasion_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_user_id INTEGER,
                new_user_id INTEGER,
                group_id INTEGER,
                confidence TEXT DEFAULT 'medium',
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await self.db.commit()

    async def get_group_settings(self, group_id: int):
        cursor = await self.db.execute("SELECT settings FROM groups WHERE group_id = ?", (group_id,))
        row = await cursor.fetchone()
        if row:
            return {**DEFAULT_SETTINGS, **json.loads(row[0])}
        return dict(DEFAULT_SETTINGS)

    async def set_group_setting(self, group_id: int, key: str, value):
        settings = await self.get_group_settings(group_id)
        settings[key] = value
        await self.db.execute(
            "INSERT OR REPLACE INTO groups (group_id, settings) VALUES (?, ?)",
            (group_id, json.dumps(settings)),
        )
        await self.db.commit()

    async def get_group_fed(self, group_id: int):
        cursor = await self.db.execute("SELECT fed_id FROM groups WHERE group_id = ?", (group_id,))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_group_fed(self, group_id: int, fed_id: str):
        await self.db.execute("UPDATE groups SET fed_id = ? WHERE group_id = ?", (fed_id, group_id))
        await self.db.commit()

    async def create_federation(self, fed_id: str, owner_id: int, name: str):
        await self.db.execute(
            "INSERT INTO federations (fed_id, owner_id, name) VALUES (?, ?, ?)",
            (fed_id, owner_id, name),
        )
        await self.db.commit()

    async def get_federation(self, fed_id: str):
        cursor = await self.db.execute(
            "SELECT fed_id, owner_id, name FROM federations WHERE fed_id = ?", (fed_id,)
        )
        return await cursor.fetchone()

    async def delete_federation(self, fed_id: str):
        await self.db.execute("DELETE FROM federations WHERE fed_id = ?", (fed_id,))
        await self.db.execute("DELETE FROM federation_bans WHERE fed_id = ?", (fed_id,))
        await self.db.execute("UPDATE groups SET fed_id = NULL WHERE fed_id = ?", (fed_id,))
        await self.db.commit()

    async def fban(self, fed_id: str, user_id: int, reason: str, banned_by: int, group_id: int):
        await self.db.execute(
            "INSERT OR REPLACE INTO federation_bans (fed_id, user_id, reason, banned_by, banned_in_group) VALUES (?, ?, ?, ?, ?)",
            (fed_id, user_id, reason, banned_by, group_id),
        )
        await self.db.commit()

    async def funban(self, fed_id: str, user_id: int):
        await self.db.execute(
            "DELETE FROM federation_bans WHERE fed_id = ? AND user_id = ?", (fed_id, user_id)
        )
        await self.db.commit()

    async def is_fed_banned(self, fed_id: str, user_id: int):
        cursor = await self.db.execute(
            "SELECT reason FROM federation_bans WHERE fed_id = ? AND user_id = ?", (fed_id, user_id)
        )
        return await cursor.fetchone()

    async def get_fed_bans(self, fed_id: str):
        cursor = await self.db.execute(
            "SELECT user_id, reason FROM federation_bans WHERE fed_id = ?", (fed_id,)
        )
        return await cursor.fetchall()

    async def get_fed_groups(self, fed_id: str):
        cursor = await self.db.execute(
            "SELECT group_id FROM groups WHERE fed_id = ?", (fed_id,)
        )
        return [r[0] for r in await cursor.fetchall()]

    async def create_event(self, group_id, creator_id, title, description, event_date, max_participants):
        cursor = await self.db.execute(
            "INSERT INTO events (group_id, creator_id, title, description, event_date, max_participants) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (group_id, creator_id, title, description, event_date, max_participants),
        )
        row = await cursor.fetchone()
        await self.db.commit()
        return row[0]

    async def get_event(self, event_id: int):
        cursor = await self.db.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        return await cursor.fetchone()

    async def get_group_events(self, group_id: int):
        cursor = await self.db.execute(
            "SELECT id, title, event_date FROM events WHERE group_id = ? ORDER BY event_date", (group_id,)
        )
        return await cursor.fetchall()

    async def delete_event(self, event_id: int):
        await self.db.execute("DELETE FROM event_rsvps WHERE event_id = ?", (event_id,))
        await self.db.execute("DELETE FROM events WHERE id = ?", (event_id,))
        await self.db.commit()

    async def rsvp_event(self, event_id: int, user_id: int, status="going"):
        await self.db.execute(
            "INSERT OR REPLACE INTO event_rsvps (event_id, user_id, status) VALUES (?, ?, ?)",
            (event_id, user_id, status),
        )
        await self.db.commit()

    async def unrsvp_event(self, event_id: int, user_id: int):
        await self.db.execute(
            "DELETE FROM event_rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id)
        )
        await self.db.commit()

    async def get_event_rsvps(self, event_id: int):
        cursor = await self.db.execute(
            "SELECT user_id, status FROM event_rsvps WHERE event_id = ?", (event_id,)
        )
        return await cursor.fetchall()

    async def create_invite(self, group_id, creator_id, invite_link, name):
        cursor = await self.db.execute(
            "INSERT INTO invites (group_id, creator_id, invite_link, name) VALUES (?, ?, ?, ?) RETURNING id",
            (group_id, creator_id, invite_link, name),
        )
        row = await cursor.fetchone()
        await self.db.commit()
        return row[0]

    async def get_invite_by_link(self, invite_link: str):
        cursor = await self.db.execute(
            "SELECT id, group_id, creator_id, uses FROM invites WHERE invite_link = ?", (invite_link,)
        )
        return await cursor.fetchone()

    async def get_invite_by_name(self, group_id: int, name: str):
        cursor = await self.db.execute(
            "SELECT id, invite_link, uses FROM invites WHERE group_id = ? AND name = ?", (group_id, name)
        )
        return await cursor.fetchone()

    async def increment_invite(self, invite_id: int):
        await self.db.execute("UPDATE invites SET uses = uses + 1 WHERE id = ?", (invite_id,))
        await self.db.commit()

    async def add_invite_use(self, invite_id: int, user_id: int):
        await self.db.execute(
            "INSERT OR IGNORE INTO invite_uses (invite_id, user_id) VALUES (?, ?)",
            (invite_id, user_id),
        )
        await self.db.commit()

    async def get_user_invites(self, group_id: int, creator_id: int):
        cursor = await self.db.execute(
            "SELECT name, invite_link, uses FROM invites WHERE group_id = ? AND creator_id = ?",
            (group_id, creator_id),
        )
        return await cursor.fetchall()

    async def get_top_inviters(self, group_id: int):
        cursor = await self.db.execute(
            "SELECT creator_id, SUM(uses) as total FROM invites WHERE group_id = ? GROUP BY creator_id ORDER BY total DESC LIMIT 10",
            (group_id,),
        )
        return await cursor.fetchall()

    async def set_captcha(self, user_id, group_id, answer, message_id):
        await self.db.execute(
            "INSERT OR REPLACE INTO captcha_states (user_id, group_id, answer, message_id, tries) VALUES (?, ?, ?, ?, 0)",
            (user_id, group_id, answer, message_id),
        )
        await self.db.commit()

    async def get_captcha(self, user_id, group_id):
        cursor = await self.db.execute(
            "SELECT answer, message_id, tries FROM captcha_states WHERE user_id = ? AND group_id = ?",
            (user_id, group_id),
        )
        return await cursor.fetchone()

    async def increment_captcha_tries(self, user_id, group_id):
        await self.db.execute(
            "UPDATE captcha_states SET tries = tries + 1 WHERE user_id = ? AND group_id = ?",
            (user_id, group_id),
        )
        await self.db.commit()

    async def delete_captcha(self, user_id, group_id):
        await self.db.execute(
            "DELETE FROM captcha_states WHERE user_id = ? AND group_id = ?",
            (user_id, group_id),
        )
        await self.db.commit()

    async def log_toxicity(self, group_id, user_id, message_text, score, action_taken):
        await self.db.execute(
            "INSERT INTO toxicity_logs (group_id, user_id, message_text, score, action_taken) VALUES (?, ?, ?, ?, ?)",
            (group_id, user_id, message_text, score, action_taken),
        )
        await self.db.commit()

    async def get_reputation(self, group_id, user_id):
        cursor = await self.db.execute(
            "SELECT score FROM reputation WHERE group_id = ? AND user_id = ?", (group_id, user_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def update_reputation(self, group_id, user_id, delta: int):
        current = await self.get_reputation(group_id, user_id)
        new_score = max(-100, min(100, current + delta))
        await self.db.execute(
            "INSERT OR REPLACE INTO reputation (group_id, user_id, score) VALUES (?, ?, ?)",
            (group_id, user_id, new_score),
        )
        await self.db.commit()
        return new_score

    async def set_rules(self, group_id, content):
        await self.db.execute(
            "INSERT OR REPLACE INTO rules (group_id, content) VALUES (?, ?)",
            (group_id, content),
        )
        await self.db.commit()

    async def get_rules(self, group_id):
        cursor = await self.db.execute("SELECT content FROM rules WHERE group_id = ?", (group_id,))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def schedule_message(self, group_id, user_id, content, send_at):
        await self.db.execute(
            "INSERT INTO scheduled_messages (group_id, user_id, content, send_at) VALUES (?, ?, ?, ?)",
            (group_id, user_id, content, send_at),
        )
        await self.db.commit()

    async def get_pending_scheduled(self):
        cursor = await self.db.execute(
            "SELECT id, group_id, content FROM scheduled_messages WHERE sent = 0 AND send_at <= datetime('now')"
        )
        return await cursor.fetchall()

    async def mark_scheduled_sent(self, msg_id: int):
        await self.db.execute("UPDATE scheduled_messages SET sent = 1 WHERE id = ?", (msg_id,))
        await self.db.commit()

    async def log_action(self, group_id, admin_id, action, target_id, reason=""):
        await self.db.execute(
            "INSERT INTO admin_actions (group_id, admin_id, action, target_id, reason) VALUES (?, ?, ?, ?, ?)",
            (group_id, admin_id, action, target_id, reason),
        )
        await self.db.commit()

    async def add_warning(self, group_id, user_id, admin_id, reason):
        await self.db.execute(
            "INSERT INTO warnings (group_id, user_id, admin_id, reason) VALUES (?, ?, ?, ?)",
            (group_id, user_id, admin_id, reason),
        )
        await self.db.execute(
            "UPDATE group_users SET warning_count = warning_count + 1 WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        )
        await self.db.commit()

    async def get_warnings(self, group_id, user_id):
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM warnings WHERE group_id = ? AND user_id = ?", (group_id, user_id)
        )
        return (await cursor.fetchone())[0]

    async def clear_warnings(self, group_id, user_id):
        await self.db.execute("DELETE FROM warnings WHERE group_id = ? AND user_id = ?", (group_id, user_id))
        await self.db.execute(
            "UPDATE group_users SET warning_count = 0 WHERE group_id = ? AND user_id = ?", (group_id, user_id)
        )
        await self.db.commit()

    async def get_user_warnings_list(self, group_id, user_id):
        cursor = await self.db.execute(
            "SELECT admin_id, reason, created_at FROM warnings WHERE group_id = ? AND user_id = ? ORDER BY created_at DESC",
            (group_id, user_id),
        )
        return await cursor.fetchall()

    async def add_flood_count(self, user_id, group_id, current_time):
        cursor = await self.db.execute(
            "SELECT count FROM flood_cache WHERE user_id = ? AND group_id = ?", (user_id, group_id)
        )
        row = await cursor.fetchone()
        if row:
            await self.db.execute(
                "UPDATE flood_cache SET count = count + 1, message_time = ? WHERE user_id = ? AND group_id = ?",
                (current_time, user_id, group_id),
            )
        else:
            await self.db.execute(
                "INSERT INTO flood_cache (user_id, group_id, message_time, count) VALUES (?, ?, ?, 1)",
                (user_id, group_id, current_time),
            )
        await self.db.commit()

    async def get_flood_count(self, user_id, group_id):
        cursor = await self.db.execute(
            "SELECT count, message_time FROM flood_cache WHERE user_id = ? AND group_id = ?", (user_id, group_id)
        )
        row = await cursor.fetchone()
        return row if row else (0, 0)

    async def reset_flood(self, user_id, group_id):
        await self.db.execute("DELETE FROM flood_cache WHERE user_id = ? AND group_id = ?", (user_id, group_id))
        await self.db.commit()

    async def get_filter(self, group_id, keyword):
        cursor = await self.db.execute(
            "SELECT response FROM filters WHERE group_id = ? AND keyword = ?", (group_id, keyword.lower())
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def add_filter(self, group_id, keyword, response):
        await self.db.execute(
            "INSERT OR REPLACE INTO filters (group_id, keyword, response) VALUES (?, ?, ?)",
            (group_id, keyword.lower(), response),
        )
        await self.db.commit()

    async def remove_filter(self, group_id, keyword):
        await self.db.execute(
            "DELETE FROM filters WHERE group_id = ? AND keyword = ?", (group_id, keyword.lower())
        )
        await self.db.commit()

    async def get_all_filters(self, group_id):
        cursor = await self.db.execute("SELECT keyword FROM filters WHERE group_id = ?", (group_id,))
        return [r[0] for r in await cursor.fetchall()]

    async def save_note(self, group_id, name, content, file_id=None, file_type=None):
        await self.db.execute(
            "INSERT OR REPLACE INTO notes (group_id, name, content, file_id, file_type) VALUES (?, ?, ?, ?, ?)",
            (group_id, name.lower(), content, file_id, file_type),
        )
        await self.db.commit()

    async def get_note(self, group_id, name):
        cursor = await self.db.execute(
            "SELECT content, file_id, file_type FROM notes WHERE group_id = ? AND name = ?", (group_id, name.lower())
        )
        return await cursor.fetchone()

    async def delete_note(self, group_id, name):
        await self.db.execute("DELETE FROM notes WHERE group_id = ? AND name = ?", (group_id, name.lower()))
        await self.db.commit()

    async def get_all_notes(self, group_id):
        cursor = await self.db.execute("SELECT name FROM notes WHERE group_id = ?", (group_id,))
        return [r[0] for r in await cursor.fetchall()]

    async def ensure_group_user(self, group_id, user_id, username, first_name):
        await self.db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name),
        )
        await self.db.execute(
            "INSERT OR IGNORE INTO group_users (group_id, user_id) VALUES (?, ?)",
            (group_id, user_id),
        )
        await self.db.execute(
            "UPDATE group_users SET message_count = message_count + 1 WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        )
        await self.db.commit()

    async def set_verified(self, group_id, user_id, verified=True):
        await self.db.execute(
            "UPDATE group_users SET verified = ? WHERE group_id = ? AND user_id = ?",
            (1 if verified else 0, group_id, user_id),
        )
        await self.db.commit()

    async def is_verified(self, group_id, user_id):
        cursor = await self.db.execute(
            "SELECT verified FROM group_users WHERE group_id = ? AND user_id = ?", (group_id, user_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_stats(self, group_id):
        cursor = await self.db.execute("SELECT COUNT(*) FROM group_users WHERE group_id = ?", (group_id,))
        members = (await cursor.fetchone())[0]
        cursor = await self.db.execute("SELECT COUNT(*) FROM warnings WHERE group_id = ?", (group_id,))
        warns = (await cursor.fetchone())[0]
        cursor = await self.db.execute("SELECT COUNT(*) FROM admin_actions WHERE group_id = ?", (group_id,))
        actions = (await cursor.fetchone())[0]
        return members, warns, actions

    # --- Shadow Ban & Evasion ---

    async def add_shadow_ban(self, user_id, banned_by, group_id, reason, original_ban_id=None):
        await self.db.execute(
            "INSERT INTO shadow_bans (user_id, original_ban_id, banned_by, group_id, reason) VALUES (?, ?, ?, ?, ?)",
            (user_id, original_ban_id, banned_by, group_id, reason),
        )
        await self.db.commit()

    async def remove_shadow_ban(self, user_id: int):
        await self.db.execute("UPDATE shadow_bans SET is_active = 0 WHERE user_id = ?", (user_id,))
        await self.db.commit()

    async def is_shadow_banned(self, user_id: int):
        cursor = await self.db.execute(
            "SELECT reason, original_ban_id FROM shadow_bans WHERE user_id = ? AND is_active = 1", (user_id,)
        )
        return await cursor.fetchone()

    async def get_shadow_bans(self):
        cursor = await self.db.execute(
            "SELECT user_id, reason, banned_by, group_id, banned_at FROM shadow_bans WHERE is_active = 1 ORDER BY banned_at DESC"
        )
        return await cursor.fetchall()

    async def get_recent_bans(self, group_id, minutes=10):
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(minutes=minutes)
        cursor = await self.db.execute(
            "SELECT target_id, action, created_at FROM admin_actions WHERE group_id = ? AND action IN ('ban', 'kick', 'shadowban') AND created_at >= ? ORDER BY created_at DESC LIMIT 5",
            (group_id, since.strftime("%Y-%m-%d %H:%M:%S")),
        )
        return await cursor.fetchall()

    async def log_evasion(self, original_user_id, new_user_id, group_id, confidence='medium'):
        await self.db.execute(
            "INSERT INTO evasion_attempts (original_user_id, new_user_id, group_id, confidence) VALUES (?, ?, ?, ?)",
            (original_user_id, new_user_id, group_id, confidence),
        )
        await self.db.commit()

    async def get_evasion_stats(self, group_id=None):
        if group_id:
            cursor = await self.db.execute("SELECT COUNT(*) FROM evasion_attempts WHERE group_id = ?", (group_id,))
        else:
            cursor = await self.db.execute("SELECT COUNT(*) FROM evasion_attempts")
        return (await cursor.fetchone())[0]

db = Database()
