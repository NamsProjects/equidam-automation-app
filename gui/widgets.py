"""
widgets.py
Core custom widgets for the Equidam Projections Uploader.
"""

import tkinter as tk
from tkinter import ttk

# Re-export InfoPanel for backward compatibility (safe conditional)
__all__ = ["ScrollableFrame", "HorizontalScrollFrame"]
try:
    from gui.info_panel import InfoPanel
    globals()["InfoPanel"] = InfoPanel
    __all__.append("InfoPanel")
except ImportError:
    try:
        from info_panel import InfoPanel
        globals()["InfoPanel"] = InfoPanel
        __all__.append("InfoPanel")
    except ImportError:
        pass


class ScrollableFrame(ttk.Frame):
    """
    A scrollable frame container.
    Content should be added to the 'body' attribute.
    """
    
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        
        # Create canvas and scrollbar
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)

        # Create the frame that will hold all content
        self.body = ttk.Frame(self.canvas)

        # Yscroll command auto-hides the scrollbar when content fits
        self.canvas.configure(yscrollcommand=self._set_yscroll)

        # Pack canvas first; scrollbar is shown on demand by _set_yscroll
        self.canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar_visible = False
        
        # Create window in canvas
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.body,
            anchor="nw"
        )
        
        # Bind events
        self.body.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Bind mousewheel globally on the toplevel so scrolling works
        # anywhere on the page (over labels, buttons, panels, etc.).
        # Routed through _on_global_mousewheel so we skip tksheet (which
        # has its own scrolling) and only act when content actually overflows.
        top = self.winfo_toplevel()
        top.bind("<MouseWheel>", self._on_global_mousewheel, add="+")
        top.bind("<Button-4>",   self._on_global_mousewheel, add="+")
        top.bind("<Button-5>",   self._on_global_mousewheel, add="+")

    def _on_global_mousewheel(self, event):
        """Page-wide mousewheel handler. Scrolls our canvas unless the
        cursor is over an inner scrollable widget (like a tksheet table)."""
        if not self._scrollbar_visible:
            return  # nothing to scroll

        # Skip if cursor isn't within our canvas region
        cx = self.canvas.winfo_rootx()
        cy = self.canvas.winfo_rooty()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if not (cx <= event.x_root < cx + cw and cy <= event.y_root < cy + ch):
            return

        # If the event widget lives inside a tksheet, let tksheet handle it
        w = event.widget
        while w is not None:
            cls = ""
            try:
                cls = w.winfo_class()
            except Exception:
                break
            # tksheet uses canvas-based MainTable/RowIndex/ColumnHeaders
            if cls in ("MainTable", "RowIndex", "ColumnHeaders") or "Sheet" in cls:
                return
            if w is self.canvas:
                break
            w = getattr(w, "master", None)

        # Scroll our canvas
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")
    
    def _set_yscroll(self, lo, hi):
        """Yscrollcommand that auto-hides the scrollbar when content fits."""
        lo, hi = float(lo), float(hi)
        if lo <= 0.0 and hi >= 1.0:
            if self._scrollbar_visible:
                self.scrollbar.pack_forget()
                self._scrollbar_visible = False
        else:
            if not self._scrollbar_visible:
                self.scrollbar.pack(side="right", fill="y")
                self._scrollbar_visible = True
        self.scrollbar.set(lo, hi)

    def _on_frame_configure(self, event=None):
        """Reset the scroll region to encompass the inner frame."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        # Scrollregion changes don't always trigger yscrollcommand — refresh explicitly
        self._refresh_scrollbar()
    
    def _on_canvas_configure(self, event):
        """Resize the inner frame to match the canvas width."""
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_window, width=canvas_width)
        # Re-evaluate scrollbar visibility after canvas resize
        self._refresh_scrollbar()

    def _refresh_scrollbar(self):
        """Re-evaluate whether the scrollbar should be visible."""
        try:
            lo, hi = self.canvas.yview()
        except Exception:
            return
        self._set_yscroll(lo, hi)


class HorizontalScrollFrame(ttk.Frame):
    """
    A horizontally scrollable container. Children added to `body` can be
    wider than the visible area; a horizontal scrollbar appears on demand.

    Used to let the user scroll between the Financial grid and the Balance
    Sheet grid when both don't fit on screen at the same time.
    """

    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self._set_xscroll)

        self.body = ttk.Frame(self.canvas)

        self.canvas.pack(side="top", fill="both", expand=True)
        self._scrollbar_visible = False

        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.body,
            anchor="nw",
        )

        self.body.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Shift+Wheel = horizontal scroll, a common convention on Windows.
        top = self.winfo_toplevel()
        top.bind("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")

    def _set_xscroll(self, lo, hi):
        """xscrollcommand that auto-hides the scrollbar when content fits."""
        lo, hi = float(lo), float(hi)
        if lo <= 0.0 and hi >= 1.0:
            if self._scrollbar_visible:
                self.hbar.pack_forget()
                self._scrollbar_visible = False
        else:
            if not self._scrollbar_visible:
                # Pack below the canvas so it sits at the bottom of the area.
                self.hbar.pack(side="bottom", fill="x", before=self.canvas)
                self._scrollbar_visible = True
        self.hbar.set(lo, hi)

    def _on_frame_configure(self, event=None):
        """Sync scrollregion to inner frame size and grow canvas vertically
        to fit its content (so the grids aren't vertically clipped)."""
        # Defer so tkinter commits all pending geometry changes first.
        self.after_idle(self._apply_scroll_region)

    def _apply_scroll_region(self):
        """Update canvas window width and scrollregion after geometry settles."""
        natural_w = self.body.winfo_reqwidth()
        natural_h = self.body.winfo_reqheight()
        canvas_w = self.canvas.winfo_width()
        target_w = max(natural_w, canvas_w)
        self.canvas.itemconfig(self.canvas_window, width=target_w)
        self.canvas.configure(scrollregion=(0, 0, target_w, natural_h))
        self.canvas.configure(height=natural_h)
        self._refresh_scrollbar()

    def _on_canvas_configure(self, event):
        """When the canvas grows wider than the content, the body should
        still occupy at least the full width; let it grow beyond when needed."""
        self.after_idle(self._apply_scroll_region)

    def _refresh_scrollbar(self):
        try:
            lo, hi = self.canvas.xview()
        except Exception:
            return
        self._set_xscroll(lo, hi)

    def _on_shift_mousewheel(self, event):
        if not self._scrollbar_visible:
            return
        cx = self.canvas.winfo_rootx()
        cy = self.canvas.winfo_rooty()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if not (cx <= event.x_root < cx + cw and cy <= event.y_root < cy + ch):
            return
        step = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(step, "units")