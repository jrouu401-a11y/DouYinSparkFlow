"""Offline real-Chromium regression check; no Douyin connection or credentials.

Run after installing Playwright Chromium:
    python -c "import runpy; runpy.run_path('tests/browser_delivery_check.py', run_name='__main__')"
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from core import tasks


HTML = """<!doctype html><meta charset="utf-8">
<div class="conversationConversationListwrapper">
  <div class="conversationConversationItemwrapper conversationConversationItemcurConversation">
    <span class="conversationConversationItemtitle">Friend</span>
    <span>[test-emoji]</span>
  </div>
</div>
<div class="RightPanelHeadertitle">Friend</div>
<div class="messageMessageBoxisFromMe"><div class="MessageItemTextbubbleTextContent">
<img title="[test-emoji]"></div></div>
<div class="messageEditorimChatEditorContainer"><div contenteditable="true"></div></div>
<button class="e2e-send-msg-btn">Send</button>
<script>
function bubble() {
  const box = document.createElement('div');
  box.className = 'messageMessageBoxisFromMe';
  box.innerHTML = '<div class="MessageItemTextbubbleTextContent"><img title="[test-emoji]"></div>';
  document.body.append(box);
}
if (sessionStorage.getItem('persisted')) bubble();
document.querySelector('button').onclick = () => {
  sessionStorage.setItem('clicks', String(Number(sessionStorage.getItem('clicks') || 0) + 1));
  document.querySelector('[contenteditable]').innerText = '';
  bubble();
  if (location.pathname === '/persist') sessionStorage.setItem('persisted', 'yes');
};
</script>"""


def main():
    bundled = Path(__file__).resolve().parents[1] / "chrome"
    if bundled.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for path, expected in [("persist", True), ("optimistic-only", False)]:
                context = browser.new_context()
                page = context.new_page()
                page.route("**/*", lambda route: route.fulfill(body=HTML, content_type="text/html"))
                page.goto(f"https://delivery-test.invalid/{path}")
                assert tasks.message_echo_count(page, "[test-emoji]") == 1, "Sidebar must not count"
                editor, baseline = tasks.prepare_message(
                    page.locator(tasks.CONVERSATION_ITEM_SELECTOR), page, "Friend", "[test-emoji]", 1000
                )
                assert tasks.message_echo_count(page, "[test-emoji]") == baseline, "Draft must not count"
                page.locator(tasks.SEND_BUTTON_SELECTOR).click()
                result = tasks.confirm_message_sent(
                    page, editor, "[test-emoji]", baseline, display_name="Friend"
                )
                assert result is expected, f"{path}: unexpected confirmation {result}"
                assert page.evaluate("sessionStorage.getItem('clicks')") == "1", "Never resubmit"
                context.close()
                print(f"PASS: {path}; emoji-aware, sidebar excluded, one click, reloaded history checked")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
