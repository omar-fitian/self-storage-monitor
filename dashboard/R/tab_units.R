# All units: every row behind the other two tabs, searchable.
#
# Layout and behaviour sit together so that one tab is one file to read.

units_tab_ui <- function() {
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
}

units_tab_server <- function(output, snapshot) {

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
