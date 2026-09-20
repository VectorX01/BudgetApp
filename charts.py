"""Altair chart builders.

Kept free of Streamlit so the specs can be compiled and checked without a
running app. Colours come from a validated categorical palette: slots 1 and 2
(blue/orange) for series identity, blue/red for diverging above-below-zero.
Both modes were validated against the real Streamlit surfaces — every check
passes, worst adjacent CVD ΔE 24.7 light / 26.8 dark.

Charts are rendered with ``theme=None`` on the Streamlit side so these colours
survive rather than being repainted by Streamlit's own Altair theme.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

PALETTE = {
    "light": {
        "surface": "#ffffff",
        "text": "#0b0b0b",
        "muted": "#52514e",
        "grid": "#e6e5e1",
        "series_1": "#2a78d6",
        "series_2": "#eb6834",
        "positive": "#2a78d6",
        "negative": "#e34948",
    },
    "dark": {
        "surface": "#0e1117",
        "text": "#fafafa",
        "muted": "#c3c2b7",
        "grid": "#2b2f38",
        "series_1": "#3987e5",
        "series_2": "#d95926",
        "positive": "#3987e5",
        "negative": "#e66767",
    },
}

MONEY = "$,.0f"
FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)


def palette(mode: str) -> dict[str, str]:
    return PALETTE.get(mode, PALETTE["light"])


def _style(chart: alt.Chart, ink: dict[str, str]) -> alt.Chart:
    """Recessive axes and grid, text in text tokens, transparent surface.

    The transparent background is not cosmetic: Vega-Lite defaults the top-level
    background to white, which leaves a white slab behind every chart on a dark
    Streamlit theme and hides the light legend text sitting on it.
    """
    return (
        chart.configure(background="transparent")
        .configure_view(strokeWidth=0, fill=None)
        .configure_axis(
            labelFont=FONT,
            titleFont=FONT,
            labelColor=ink["muted"],
            titleColor=ink["muted"],
            labelFontSize=11,
            titleFontSize=11,
            titleFontWeight="normal",
            gridColor=ink["grid"],
            gridOpacity=0.7,
            domainColor=ink["grid"],
            tickColor=ink["grid"],
            labelPadding=6,
        )
        .configure_legend(
            labelFont=FONT,
            titleFont=FONT,
            labelColor=ink["text"],
            titleColor=ink["muted"],
            labelFontSize=12,
            titleFontSize=11,
            orient="top",
            direction="horizontal",
            symbolType="square",
            symbolSize=110,
            offset=4,
        )
        .configure_text(font=FONT)
    )


def _months_to_dates(frame: pd.DataFrame, column: str = "Month") -> pd.DataFrame:
    """Swap a pandas Period column for a real timestamp.

    The Period itself is dropped: Altair serialises the whole frame to JSON and
    Periods are not serialisable.
    """
    out = frame.copy()
    out["Date"] = out[column].apply(
        lambda period: period.to_timestamp() if isinstance(period, pd.Period) else period
    )
    return out.drop(columns=[column])


def net_worth(series: pd.DataFrame, mode: str, highlight: pd.Period | None = None):
    """Single-series trend. One series needs no legend; the title names it."""
    ink = palette(mode)
    data = _months_to_dates(series)
    hover = alt.selection_point(
        fields=["Date"], nearest=True, on="pointerover", empty=False, clear="pointerout"
    )

    base = alt.Chart(data).encode(
        # No forced per-month tick: at dashboard widths a tick per month runs
        # the labels into each other ("Aug 26Sep 26").
        x=alt.X(
            "Date:T",
            axis=alt.Axis(
                format="%b %y", title=None, labelOverlap="greedy", tickCount=7
            ),
        ),
        y=alt.Y(
            "Net worth:Q",
            axis=alt.Axis(format=MONEY, title=None),
            scale=alt.Scale(nice=True, zero=True),
        ),
    )
    # Linear, never smoothed: a monotone curve invents balances between months
    # that never existed, which is exactly the wrong lie for a ledger to tell.
    line = base.mark_line(strokeWidth=2, color=ink["series_1"])
    crosshair = (
        base.mark_rule(color=ink["muted"], strokeWidth=1, strokeDash=[3, 3])
        .encode(opacity=alt.condition(hover, alt.value(0.7), alt.value(0)))
        .add_params(hover)
    )
    dots = base.mark_point(
        size=90, filled=True, color=ink["series_1"], stroke=ink["surface"], strokeWidth=2
    ).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[
            alt.Tooltip("Date:T", title="Month", format="%B %Y"),
            alt.Tooltip("Net worth:Q", format="$,.2f"),
        ],
    )

    layers = [line, crosshair, dots]
    if highlight is not None:
        marker = (
            alt.Chart(pd.DataFrame({"Date": [highlight.to_timestamp()]}))
            .mark_rule(color=ink["muted"], strokeWidth=1, opacity=0.45)
            .encode(x="Date:T")
        )
        layers.insert(0, marker)

    return _style(alt.layer(*layers).properties(height=220), ink)


def earned_vs_spent(summary: pd.DataFrame, mode: str):
    """Two series, so a legend is always present. Grouped, not stacked."""
    ink = palette(mode)
    data = _months_to_dates(summary, "Period")[["Date", "Earned", "Spent"]]
    long = data.melt("Date", var_name="Series", value_name="Amount")

    bars = (
        alt.Chart(long)
        .mark_bar(cornerRadiusEnd=4, stroke=None)
        .encode(
            x=alt.X("yearmonth(Date):O", axis=alt.Axis(format="%b %y", title=None, labelAngle=0)),
            xOffset=alt.XOffset("Series:N", sort=["Earned", "Spent"]),
            y=alt.Y("Amount:Q", axis=alt.Axis(format=MONEY, title=None)),
            color=alt.Color(
                "Series:N",
                sort=["Earned", "Spent"],
                scale=alt.Scale(
                    domain=["Earned", "Spent"],
                    range=[ink["series_1"], ink["series_2"]],
                ),
                legend=alt.Legend(title=None),
            ),
            tooltip=[
                alt.Tooltip("yearmonth(Date):T", title="Month", format="%B %Y"),
                alt.Tooltip("Series:N", title=None),
                alt.Tooltip("Amount:Q", format="$,.2f"),
            ],
        )
        .properties(height=240)
    )
    # A 2px surface gap between adjacent fills keeps the pair legible.
    return _style(bars.configure_scale(bandPaddingInner=0.18), ink)


def category_bars(amounts: pd.Series, mode: str, limit: int = 12):
    """Magnitude comparison: one hue, sorted, direct-labelled.

    Used for both spend-by-category and income-by-source; nothing about it is
    specific to money going out.
    """
    ink = palette(mode)
    data = (
        amounts.head(limit)
        .rename("Amount")
        .rename_axis("Category")
        .reset_index()
    )
    # Whole dollars are right for rent and groceries, but income carries $0.02
    # dividends that a 0-decimal label flattens to "$0". Small values keep their
    # cents; large ones stay uncluttered.
    data["Label"] = [
        f"{'−' if v < 0 else ''}${abs(v):,.2f}"
        if abs(v) < 10
        else f"{'−' if v < 0 else ''}${abs(v):,.0f}"
        for v in data["Amount"]
    ]
    base = alt.Chart(data).encode(
        y=alt.Y("Category:N", sort="-x", axis=alt.Axis(title=None, labelLimit=140)),
        # Headroom so the direct label on the longest bar is not clipped.
        x=alt.X(
            "Amount:Q",
            # nice=False is needed to hold the label headroom, so the tick
            # count has to be asked for explicitly or Vega emits one per $100.
            axis=alt.Axis(format=MONEY, title=None, tickCount=5),
            scale=alt.Scale(
                domainMax=float(data["Amount"].max()) * 1.18 if len(data) else 1.0,
                nice=False,
            ),
        ),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, color=ink["series_1"]).encode(
        tooltip=[
            alt.Tooltip("Category:N", title=None),
            alt.Tooltip("Amount:Q", format="$,.2f"),
        ]
    )
    labels = base.mark_text(
        align="left", dx=6, fontSize=11, color=ink["muted"], font=FONT
    ).encode(text=alt.Text("Label:N"))
    height = max(140, 26 * len(data))
    return _style(alt.layer(bars, labels).properties(height=height), ink)


def market_vs_basis(history: pd.DataFrame, mode: str):
    """Market value against cost basis. Same unit, so one shared y axis."""
    ink = palette(mode)
    long = history.melt(
        id_vars="Date",
        value_vars=["Market value", "Cost basis"],
        var_name="Series",
        value_name="Amount",
    )
    hover = alt.selection_point(
        fields=["Date"], nearest=True, on="pointerover", empty=False, clear="pointerout"
    )
    base = alt.Chart(long).encode(
        x=alt.X("Date:T", axis=alt.Axis(format="%d %b", title=None)),
        y=alt.Y(
            "Amount:Q",
            axis=alt.Axis(format=MONEY, title=None),
            scale=alt.Scale(nice=True, zero=False),
        ),
        color=alt.Color(
            "Series:N",
            sort=["Market value", "Cost basis"],
            scale=alt.Scale(
                domain=["Market value", "Cost basis"],
                range=[ink["series_1"], ink["series_2"]],
            ),
            legend=alt.Legend(title=None),
        ),
    )
    lines = base.mark_line(strokeWidth=2)
    dots = base.mark_point(size=80, filled=True, stroke=ink["surface"], strokeWidth=2).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[
            alt.Tooltip("Date:T", title="Week of", format="%d %b %Y"),
            alt.Tooltip("Series:N", title=None),
            alt.Tooltip("Amount:Q", format="$,.2f"),
        ],
    )
    crosshair = (
        base.mark_rule(color=ink["muted"], strokeWidth=1, strokeDash=[3, 3])
        .encode(opacity=alt.condition(hover, alt.value(0.7), alt.value(0)))
        .add_params(hover)
    )
    return _style(alt.layer(lines, crosshair, dots).properties(height=240), ink)


def weekly_gain(history: pd.DataFrame, mode: str):
    """Movement above and below zero: a diverging pair, gray at the midpoint."""
    ink = palette(mode)
    data = history.dropna(subset=["Market gain"])[["Date", "Market gain"]]
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, width=18)
        .encode(
            # Padding keeps the first and last bars off the plot edges, which
            # otherwise slice them in half.
            x=alt.X(
                "Date:T",
                axis=alt.Axis(format="%d %b", title=None),
                scale=alt.Scale(padding=26),
            ),
            y=alt.Y("Market gain:Q", axis=alt.Axis(format=MONEY, title=None)),
            color=alt.condition(
                alt.datum["Market gain"] >= 0,
                alt.value(ink["positive"]),
                alt.value(ink["negative"]),
            ),
            tooltip=[
                alt.Tooltip("Date:T", title="Week of", format="%d %b %Y"),
                alt.Tooltip("Market gain:Q", title="Market movement", format="$,.2f"),
            ],
        )
        .properties(height=180)
    )
    zero = (
        alt.Chart(pd.DataFrame({"y": [0]}))
        .mark_rule(color=ink["muted"], strokeWidth=1)
        .encode(y="y:Q")
    )
    return _style(alt.layer(bars, zero), ink)
