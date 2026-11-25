"""The explorer element in a real browser: one WebGL context, framework-settable view, readable 2D text,
a release mark, popovers whose close button clears their heading."""
import json
import unittest

from tests.generator import examples_directory, skill_directory, example_text
from tests.test_explorer_component import model_of

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    sync_playwright = None

component = (skill_directory / "explorer" / "wire-harness-explorer.js").read_text()
example_model = json.loads((examples_directory / "sensor-branch" / "sensor-branch.harness.json").read_text())
ten_branch_model = json.loads((examples_directory / "ten-branches" / "ten-branches.harness.json").read_text())

# Count every WebGL context the page makes, and keep them so a test can see whether each was released.
context_counter = """
window.contexts = [];
const getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
  const context = getContext.call(this, kind, ...rest);
  if (kind.startsWith("webgl") && context && !window.contexts.includes(context)) window.contexts.push(context);
  return context;
};
"""


def launch(playwright):
    """Chromium as Playwright installs it, or else the machine's own Chrome."""
    try:
        return playwright.chromium.launch()
    except PlaywrightError:
        return playwright.chromium.launch(channel="chrome")


@unittest.skipUnless(sync_playwright, "Playwright is not installed")
class ExplorerBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.browser = launch(cls.playwright)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def page(self, width: int = 1100, body: str = ""):
        """A page with the component loaded and the given body, at the given width."""
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        self.addCleanup(page.close)
        page.set_content(f'<!doctype html><body style="margin:0">{body}<script>{context_counter}</script>'
                         f'<script type="module">{component}</script></body>')
        page.wait_for_function("customElements.get('wire-harness-explorer') !== undefined")
        return page

    def show(self, page, model: dict, view: str = "3d") -> None:
        page.evaluate("""([model, view]) => {
            const element = document.createElement("wire-harness-explorer");
            element.setAttribute("view", view);
            element.harness = model;
            document.body.append(element);
        }""", [model, view])

    def test_setting_the_harness_again_and_again_keeps_one_webgl_context(self) -> None:
        page = self.page()
        self.show(page, example_model)
        page.evaluate("model => { const e = document.querySelector('wire-harness-explorer'); for (let i = 0; i < 20; i++) e.harness = model; }",
                      ten_branch_model)
        self.assertEqual(page.evaluate("window.contexts.length"), 1)

    def test_a_2d_view_makes_no_webgl_context_until_3d_is_shown(self) -> None:
        page = self.page()
        self.show(page, example_model, "2d")
        self.assertEqual(page.evaluate("window.contexts.length"), 0)
        page.click("button[data-view='3d']")  # within the shadow root: Playwright pierces it
        self.assertEqual(page.evaluate("window.contexts.length"), 1)

    def test_removing_the_element_releases_its_context(self) -> None:
        page = self.page()
        self.show(page, example_model)
        page.evaluate("document.querySelector('wire-harness-explorer').remove()")
        self.assertTrue(page.evaluate("window.contexts[0].isContextLost()"))

    # Chrome keeps about 16 WebGL contexts a page; past that it drops the oldest, blanking its view.
    def test_many_explorers_on_one_page_share_one_context_and_all_draw(self) -> None:
        page = self.page()
        for _ in range(24):
            self.show(page, example_model)
        self.assertEqual(page.evaluate("window.contexts.length"), 1)
        drawn = page.evaluate("""() => [...document.querySelectorAll('wire-harness-explorer')].map((element) => {
            const canvas = element.shadowRoot.querySelector('canvas');
            const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
            return pixels.some((value, index) => index % 4 === 3 && value > 0);
        })""")
        self.assertEqual(drawn, [True] * 24)

    # React 19 sets a property the element defines instead of its attribute.
    def test_the_view_can_be_set_as_a_property_before_and_after_the_element_is_placed(self) -> None:
        page = self.page()
        state = page.evaluate("""model => {
            const element = document.createElement("wire-harness-explorer");
            element.view = "2d";
            element.harness = model;
            document.body.append(element);
            const before = [element.getAttribute("view"), element.shadowRoot.querySelector(".planHolder").hidden];
            element.view = "3d";
            return [...before, element.getAttribute("view"), element.view];
        }""", example_model)
        self.assertEqual(state, ["2d", False, "3d", "3d"])

    def test_a_harness_whose_checks_failed_is_marked_not_for_release(self) -> None:
        page = self.page()
        self.show(page, {**example_model, "release": {"errors": 2, "warnings": 1, "for_release": False}})
        mark = page.locator("wire-harness-explorer .release")
        self.assertEqual(mark.inner_text(), "NOT FOR RELEASE · 2 check errors")
        self.show(page, example_model)
        self.assertEqual(page.locator("wire-harness-explorer >> nth=1 >> .release").count(), 0)

    def test_2d_text_is_readable_at_phone_and_desktop_widths(self) -> None:
        for width in (390, 1100):
            for model in (example_model, ten_branch_model):
                page = self.page(width)
                self.show(page, model, "2d")
                heights = page.evaluate("""() => [...document.querySelector('wire-harness-explorer').shadowRoot
                    .querySelectorAll('svg.plan text.name')].map((text) => text.getBoundingClientRect().height)""")
                self.assertTrue(heights)
                self.assertGreaterEqual(min(heights), 11, f"{model['title']} at {width} px")
                self.assertLessEqual(max(heights), 20, f"{model['title']} at {width} px")

    def test_a_popovers_close_button_never_covers_its_heading(self) -> None:
        # The connector of the gantry run whose heading the close button covered, and one whose part
        # number is a single word longer than a phone-width popover.
        for part_number in ("TBD (printed part)", "AMPHENOLAC4FDZSNSBULKHEADPRINTEDPARTREVISIONTHREEDRAFT"):
            for width in (390, 520, 1100):
                self.assert_close_clears_heading(part_number, width)

    def assert_close_clears_heading(self, part_number: str, width: int) -> None:
        long_label = {**example_model, "connectors": [{**c, "label": "SNS BULKHEAD", "part_number": part_number}
                                                       if c["id"] == "J1" else c for c in example_model["connectors"]]}
        if True:
            page = self.page(width)
            self.show(page, long_label, "2d")
            page.locator("wire-harness-explorer [data-connector='J1'] text.name").click()
            overlap = page.evaluate("""() => {
                const popover = document.querySelector('wire-harness-explorer').shadowRoot.querySelector('.popover');
                const close = popover.querySelector('.close').getBoundingClientRect();
                const range = document.createRange();
                range.selectNodeContents(popover.querySelector('h3'));
                return [...range.getClientRects()].some((r) => r.left < close.right && close.left < r.right && r.top < close.bottom && close.top < r.bottom);
            }""")
            self.assertFalse(overlap, f"{part_number} at {width} px")


if __name__ == "__main__":
    unittest.main()
