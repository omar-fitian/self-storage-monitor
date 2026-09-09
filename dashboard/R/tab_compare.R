compare_tab_ui <- function() {
  tabItem(
    tabName = "compare",
    fluidRow(
      box(
        title = "Same footprint, both chains", status = "primary",
        solidHeader = TRUE, width = 12,
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
  )
}

compare_tab_server <- function(output, snapshot, filtered, footprints) {

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
    comparable <- head_to_head()$unit_label
    data <- snapshot() |> filter(unit_label %in% comparable, !is.na(price_per_sqft))
    validate(need(nrow(data) > 0,
                  "No footprint is currently rented by both chains under these filters."))

    order <- intersect(footprints, comparable)
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

        xaxis = list(title = "", type = "date", tickformat = "%b %d",
                     nticks = max(1, min(n_distinct(daily$date), 8))),
        yaxis = list(title = "Median $ / sq ft", rangemode = "tozero"),
        legend = list(orientation = "h", y = -0.25)
      )
  })
}
