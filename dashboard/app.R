# Self-Storage Monitor Dashboard.
#
# Reads data/units.csv (written by scraper.py), which holds one row per
# rentable unit per capture date.
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

CHAIN_LABELS <- c(cubesmart = "CubeSmart", publicstorage = "Public Storage")

# --- Data ------------------------------------------------------------------

load_units <- function(path = "data/units.csv") {
  if (!file.exists(path)) {
    stop("No data at '", path, "'. Generate it with: python scraper.py", call. = FALSE)
  }
  read_csv(path, show_col_types = FALSE) |>
    mutate(
      date = as.Date(date),
      chain = coalesce(unname(CHAIN_LABELS[source]), source),
      is_parking = grepl("parking|vehicle|rv|boat", category, ignore.case = TRUE),
      # Parking spaces have no footprint -- chains sell them by length, or by
      # no dimension at all -- so rate per square foot is undefined for them.
      price_per_sqft = ifelse(is.na(area_sqft), NA_real_, price / area_sqft),
      # Both chains discount an online rate off a higher walk-in rate. Keeping
      # both lets a rate cut be told apart from a deeper promotion.
      discount_pct = ifelse(is.na(regular_price), NA_real_,
                            (1 - price / regular_price) * 100)
    )
}

money <- function(x, digits = 2) {
  ifelse(is.na(x), "–", paste0("$", formatC(x, format = "f", digits = digits, big.mark = ",")))
}

# Footprints ordered by area, so filters and axes read small -> large.
footprint_levels <- function(units) {
  units |>
    distinct(unit_label, area_sqft) |>
    arrange(is.na(area_sqft), area_sqft, unit_label) |>
    pull(unit_label)
}

# --- Layout ----------------------------------------------------------------

ui <- dashboardPage(
  dashboardHeader(title = "Self-Storage Monitor"),

  dashboardSidebar(
    sidebarMenu(
      menuItem("Facility map", tabName = "map", icon = icon("map")),
      menuItem("Head to head", tabName = "compare", icon = icon("scale-balanced")),
      menuItem("All units", tabName = "units", icon = icon("table"))
    ),
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
    "))),

    tabItems(
      tabItem(
        tabName = "map",
        fluidRow(
          valueBoxOutput("facilities_box", width = 3),
          valueBoxOutput("units_box", width = 3),
          valueBoxOutput("sqft_box", width = 3),
          valueBoxOutput("updated_box", width = 3)
        ),
        fluidRow(
          box(
            title = "Facilities by median price per square foot",
            status = "primary", solidHeader = TRUE, width = 12,
            p(class = "note",
              "Rate per square foot normalised across unit sizes."),
            leafletOutput("map", height = "540px")
          )
        )
      ),

      tabItem(
        tabName = "compare",
        fluidRow(
          box(
            title = "Same footprint, both chains", status = "primary",
            solidHeader = TRUE, width = 12,
            p(class = "note",
              "Only footprints both chains actually rent, so every row compares",
              "like with like. Median of the advertised starting rates."),
            DT::dataTableOutput("head_to_head")
          )
        ),
        fluidRow(
          box(
            title = "Rate per square foot by unit size", status = "info",
            solidHeader = TRUE, width = 7,
            plotlyOutput("sqft_distribution", height = "360px")
          ),
          box(
            title = "Median rate per square foot over time", status = "info",
            solidHeader = TRUE, width = 5,
            plotlyOutput("trend", height = "360px")
          )
        )
      ),

      tabItem(
        tabName = "units",
        fluidRow(
          box(
            title = "Every tracked unit (latest capture)", status = "primary",
            solidHeader = TRUE, width = 12,
            p(class = "note",
              HTML(paste(
                "<b>Size</b> is the chain's own designation: a footprint where",
                "one is published, otherwise what the chain calls the space --",
                "an uncovered parking spot has no dimensions to state, so it",
                "has no square footage either.<br>",
                "<b>Online</b> is the promotional rate a customer pays to book",
                "online; <b>Walk-in</b> is the undiscounted rate it is measured",
                "against, and <b>Off</b> is the gap between them.<br>",
                "<b>Category</b> is each chain's own marketing label, kept for",
                "reference only. It is not comparable across chains: CubeSmart",
                "labels a 75&nbsp;sq&nbsp;ft unit \"small\", and Public Storage",
                "publishes no such label at all."
              ))),
            DT::dataTableOutput("unit_table")
          )
        )
      )
    )
  )
)

# --- Behaviour -------------------------------------------------------------

server <- function(input, output, session) {

  # The CSV is written once a day by the scraper and never during a session,
  # so this is a constant, not a reactive.
  units <- load_units()

  updateSelectInput(session, "chain", choices = sort(unique(units$chain)))
  updateSelectInput(session, "city", choices = sort(unique(units$city)))
  updateSelectInput(session, "footprint", choices = footprint_levels(units))

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

  # ---- Summary boxes ----

  output$facilities_box <- renderValueBox({
    valueBox(n_distinct(snapshot()$street, snapshot()$postal_code), "Facilities",
             icon = icon("warehouse"), color = "blue")
  })

  output$units_box <- renderValueBox({
    valueBox(nrow(snapshot()), "Units priced", icon = icon("box"), color = "purple")
  })

  output$sqft_box <- renderValueBox({
    rates <- snapshot()$price_per_sqft
    rates <- rates[!is.na(rates)]
    valueBox(if (length(rates)) money(median(rates)) else "–",
             "Median rate / sq ft", icon = icon("dollar-sign"), color = "green")
  })

  output$updated_box <- renderValueBox({
    dates <- filtered()$date
    valueBox(if (length(dates)) format(max(dates), "%b %d, %Y") else "–",
             "Last updated", icon = icon("calendar"), color = "yellow")
  })

  # ---- Map ----

  output$map <- renderLeaflet({
    by_facility <- snapshot() |>
      group_by(chain, street, city, state, postal_code, lat, lng) |>
      summarise(
        rate_sqft = median(price_per_sqft, na.rm = TRUE),
        units = n(),
        cheapest = min(price),
        .groups = "drop"
      ) |>
      # A facility renting only parking has no rate per square foot to plot.
      filter(!is.na(rate_sqft))
    validate(need(nrow(by_facility) > 0, "No units with a footprint match these filters."))

    palette <- colorNumeric("YlOrRd", domain = by_facility$rate_sqft)

    leaflet(by_facility) |>
      # Plain OpenStreetMap tiles: no API key, no usage ceiling to trip over.
      addTiles() |>
      addCircleMarkers(
        lng = ~lng, lat = ~lat,
        radius = 8, stroke = TRUE, color = "#444", weight = 1,
        fillColor = ~palette(rate_sqft), fillOpacity = 0.9,
        label = ~street,
        popup = ~paste0(
          "<b>", street, "</b><br>", city, ", ", state, " ", postal_code,
          "<br><i>", chain, "</i><br><br>",
          "Median rate: ", money(rate_sqft), " / sq ft<br>",
          "Cheapest unit: ", money(cheapest, 0), "<br>",
          "Units priced: ", units
        )
      ) |>
      addLegend(
        position = "bottomright", pal = palette, values = ~rate_sqft,
        title = "$ / sq ft", labFormat = labelFormat(prefix = "$"), opacity = 1
      )
  })

  # ---- Head to head ----

  head_to_head <- reactive({
    snapshot() |>
      filter(!is.na(area_sqft)) |>
      group_by(unit_label, area_sqft, chain) |>
      summarise(median_price = median(price), n = n(), .groups = "drop") |>
      pivot_wider(names_from = chain, values_from = c(median_price, n)) |>
      # Only footprints both chains actually rent are comparable.
      filter(if_all(starts_with("median_price_"), ~ !is.na(.x))) |>
      arrange(area_sqft)
  })

  output$head_to_head <- DT::renderDataTable({
    table <- head_to_head()
    chains <- sub("^median_price_", "", grep("^median_price_", names(table), value = TRUE))
    # Guarding on nrow() is not enough: with one chain selected pivot_wider still
    # returns populated rows, and chains[2] would be NA all the way to an empty
    # table with no explanation.
    validate(need(length(chains) == 2, "Select both chains to compare them."))
    validate(need(nrow(table) > 0,
                  "No footprint is currently rented by both chains under these filters."))
    a <- table[[paste0("median_price_", chains[1])]]
    b <- table[[paste0("median_price_", chains[2])]]

    display <- tibble(
      Unit = table$unit_label,
      `Sq ft` = table$area_sqft,
      A = a, `units A` = table[[paste0("n_", chains[1])]],
      B = b, `units B` = table[[paste0("n_", chains[2])]],
      `Difference (%)` = round((a - b) / b * 100, 1)
    )
    names(display)[c(3, 5)] <- chains
    names(display)[c(4, 6)] <- paste("n", chains)

    DT::datatable(
      display, rownames = FALSE,
      options = list(pageLength = 15, dom = "t", ordering = FALSE)
    ) |>
      DT::formatCurrency(chains, currency = "$", digits = 0) |>
      DT::formatStyle(
        "Difference (%)",
        color = DT::styleInterval(0, c("#2e7d32", "#c62828")),
        fontWeight = "bold"
      )
  })

  output$sqft_distribution <- renderPlotly({
    # Restricted to the footprints both chains rent, matching the table above.
    # Showing all ~36 footprints (down to 1x2 lockers) makes the axis unreadable
    # and most of those sizes have only one chain in them anyway.
    comparable <- head_to_head()$unit_label
    data <- snapshot() |> filter(unit_label %in% comparable, !is.na(price_per_sqft))
    validate(need(nrow(data) > 0,
                  "No footprint is currently rented by both chains under these filters."))

    order <- intersect(footprint_levels(units), comparable)
    data$unit_label <- factor(data$unit_label, levels = order)

    plot_ly(data, x = ~unit_label, y = ~price_per_sqft, color = ~chain, type = "box",
            boxpoints = "all", jitter = 0.3, pointpos = 0,
            hovertext = ~paste0(street, " · ", money(price, 0)), hoverinfo = "text+y") |>
      layout(
        boxmode = "group",
        xaxis = list(title = "", categoryorder = "array", categoryarray = order),
        yaxis = list(title = "Advertised rate ($ / sq ft)", rangemode = "tozero"),
        legend = list(orientation = "h", y = -0.18)
      )
  })

  output$trend <- renderPlotly({
    daily <- filtered() |>
      filter(!is.na(price_per_sqft)) |>
      group_by(date, chain) |>
      summarise(rate = median(price_per_sqft), .groups = "drop")
    validate(need(nrow(daily) > 0, "No units match these filters."))

    plot_ly(daily, x = ~date, y = ~rate, color = ~chain,
            type = "scatter", mode = "lines+markers") |>
      layout(
        # One tick per capture date. Without capping nticks, a log with a
        # single date makes plotly zoom the axis down to microseconds around
        # that one point and label it with meaningless sub-second times.
        xaxis = list(title = "", type = "date", tickformat = "%b %d",
                     nticks = max(1, min(n_distinct(daily$date), 8))),
        yaxis = list(title = "Median $ / sq ft", rangemode = "tozero"),
        legend = list(orientation = "h", y = -0.25)
      )
  })

  # ---- All units ----

  output$unit_table <- DT::renderDataTable({
    table <- snapshot() |>
      mutate(
        Address = paste0(street, ", ", city, ", ", state, " ", postal_code),
        Height = ifelse(is.na(height_ft), "–", paste0(height_ft, " ft"))
      ) |>
      select(Chain = chain, Address, Size = unit_label, `Sq ft` = area_sqft,
             Height, Category = category, Online = price,
             `Walk-in` = regular_price, `Off` = discount_pct,
             `$ / sq ft` = price_per_sqft) |>
      arrange(Chain, Address, is.na(`Sq ft`), `Sq ft`)
    validate(need(nrow(table) > 0, "No units match these filters."))

    DT::datatable(table, rownames = FALSE, filter = "top",
                  options = list(pageLength = 15)) |>
      DT::formatCurrency(c("Online", "Walk-in"), currency = "$", digits = 2) |>
      DT::formatRound("Off", digits = 0) |>
      DT::formatCurrency("$ / sq ft", currency = "$", digits = 2)
  })
}

shinyApp(ui, server)
