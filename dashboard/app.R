# Self-Storage Monitor Dashboard.
#
# Run from the repository root:
#   Rscript -e "shiny::runApp('dashboard')"


library(shiny)
library(shinydashboard)
library(dplyr)
library(tidyr)
library(readr)
library(DT)
library(leaflet)
library(plotly)

ui <- dashboard_ui()

server <- function(input, output, session) {

  loaded <- units_snapshot()
  units <- loaded$units

  # Prices that are days old look exactly like current ones, so a fallback has
  # to announce itself. The wording covers either fallback -- an earlier fetch
  # or the bundled copy -- by naming the capture date rather than the source.
  output$stale_banner <- renderUI({
    if (!loaded$stale) return(NULL)
    div(
      class = "stale-banner",
      icon("triangle-exclamation"),
      strong(" Live data unavailable."),
      sprintf(paste("GitHub could not be reached, so these are the most recent",
                    "rates this dashboard has -- captured through %s."),
              format(max(units$date), "%b %d, %Y")),
      actionButton("retry_fetch", "Try again", icon = icon("rotate"),
                   class = "btn-xs stale-retry")
    )
  })

  # The forced fetch refills the shared cache, so every other open session
  # picks up the recovery too; reloading re-runs this one against it. A reload
  # rather than a reactive chain: the file changes once a day, and making the
  # whole dashboard reactive to earn one button would be a poor trade.
  observeEvent(input$retry_fetch, {
    units_snapshot(force = TRUE)
    session$reload()
  })

  footprints <- footprint_levels(units)
  updateSelectInput(session, "chain", choices = sort(unique(units$chain)))
  updateSelectInput(session, "city", choices = sort(unique(units$city)))
  updateSelectInput(session, "footprint", choices = footprints)

  apply_filters <- function(data) {
    if (isTRUE(input$hide_parking))  data <- filter(data, !is_parking)
    if (length(input$chain))     data <- filter(data, chain %in% input$chain)
    if (length(input$city))      data <- filter(data, city %in% input$city)
    if (length(input$footprint)) data <- filter(data, unit_label %in% input$footprint)
    data
  }

  # Each facility's most recent capture. Chains can be scraped on different days,
  # so "latest" is resolved per facility rather than with one global date -- and
  # before the filters rather than after. Filtering first would let a facility
  # whose current rows are all excluded fall back to an older date, and the app
  # would present yesterday's prices as today's.
  latest <- units |>
    group_by(source, street, postal_code) |>
    filter(date == max(date)) |>
    ungroup()

  # snapshot() is what is on the market now; filtered() keeps the full history,
  # which only the trend chart needs.
  snapshot <- reactive(apply_filters(latest))
  filtered <- reactive(apply_filters(units))

  map_tab_server(output, snapshot, filtered)
  compare_tab_server(output, snapshot, filtered, footprints)
  units_tab_server(output, snapshot)
}

shinyApp(ui, server)
