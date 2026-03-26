import unittest
from pathlib import Path


class ChatUiMarkersTests(unittest.TestCase):
    def test_chat_tab_and_layout_markers(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js = (root / "static" / "app.js").read_text(encoding="utf-8")
        css = (root / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-target="chat"', html)
        self.assertIn('id="panel-chat"', html)
        self.assertIn('id="chat-conversations-list"', html)
        self.assertIn('id="chat-messages"', html)
        self.assertIn('id="chat-composer"', html)
        self.assertIn('id="chat-conn-dot"', html)
        self.assertIn('id="chat-lead-tray"', html)
        self.assertIn('id="chat-lead-tray-body"', html)

        self.assertIn('async function loadChatConversations', js)
        self.assertIn('/api/chat/conversations', js)
        self.assertIn('/api/chat/send', js)
        self.assertIn('/api/chat/link-lead', js)
        self.assertIn('renderChatConnection', js)
        self.assertIn('renderChatLeadTray', js)
        self.assertIn('chatFriendlyTitle', js)
        self.assertIn('Sem conversas reais no WhatsApp', js)
        self.assertNotIn('item.name || item.phone || item.id', js)

        self.assertIn('.chat-shell', css)
        self.assertIn('.chat-col-actions', css)
        self.assertIn('.chat-conv-item', css)
        self.assertIn('.chat-messages', css)
        self.assertIn('.chat-lead-tray', css)
        self.assertIn('.chat-empty-state', css)


if __name__ == "__main__":
    unittest.main()
