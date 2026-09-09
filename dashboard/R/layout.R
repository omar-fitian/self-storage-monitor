dashboard_ui <- function() {
  dashboardPage(
    dashboardHeader(title = "Self-Storage Monitor"),

    dashboardSidebar(
      sidebarMenu(
        menuItem("Facility map", tabName = "map", icon = icon("map")),
        menuItem("Head to head", tabName = "compare", icon = icon("scale-balanced")),
        menuItem("All units", tabName = "units", icon = icon("table"))
      ),
      # Choices are filled in by the server, from whichever data actually loaded.
      selectInput("chain", "Chain", choices = NULL, multiple = TRUE),
      selectInput("city", "City", choices = NULL, multiple = TRUE),
      selectInput("footprint", "Unit size", choices = NULL, multiple = TRUE),
      checkboxInput("hide_parking", "Exclude parking spaces", value = TRUE),
      helpText(HTML("&nbsp;&nbsp;Leave a filter empty to include everything."))
    ),

    dashboardBody(
      tags$head(tags$style(HTML("
        .content-wrapper, .right-side { background-color: #f4f6f9; }
        .box { border-radius: 4px; }
        .small-box h3 { font-size: 28px; }
        .note { color: #6b7a86; font-size: 13px; margin: 0 0 10px; }
        .stale-banner { background: #fcf3cd; border: 1px solid #f0d98c;
                        border-radius: 4px; color: #6b5310; font-size: 14px;
                        margin-bottom: 15px; padding: 10px 14px; }
        .stale-retry { background: #fff; border-color: #d6bf72; color: #6b5310;
                       margin-left: 10px; }
      "))),

      # Above the tabs, so it is seen whichever one a visitor lands on.
      uiOutput("stale_banner"),

      tabItems(
        map_tab_ui(),
        compare_tab_ui(),
        units_tab_ui()
      )
    )
  )
}
