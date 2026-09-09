# Facility map: the four headline numbers, and every facility placed and
# coloured by what it charges per square foot.
#
# Layout and behaviour sit together so that one tab is one file to read. It is
# the shape a Shiny module takes, without the namespacing a single instance of
# each tab would not use.

map_tab_ui <- function() {
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
  )
}

map_tab_server <- function(output, snapshot, filtered) {

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
}
