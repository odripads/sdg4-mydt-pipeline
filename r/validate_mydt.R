# Independent R implementation of the two core arithmetic checks
# (F + M = T, and age table total = grade table total), reading the Excel
# templates directly with readxl. Used to cross-check the Python pipeline:
# both must flag the same cells.
#
#   Rscript r/validate_mydt.R data/submissions output/qc/qc_log.csv
#
# Needs: readxl, dplyr, tidyr

suppressPackageStartupMessages({
  library(readxl)
  library(dplyr)
  library(tidyr)
})

args <- commandArgs(trailingOnly = TRUE)
sub_dir <- if (length(args) >= 1) args[1] else "data/submissions"
py_log <- if (length(args) >= 2) args[2] else "output/qc/qc_log.csv"

YEAR_ROW <- 4; SEX_ROW <- 5; FIRST_ROW <- 6; FIRST_COL <- 5

read_sheet <- function(path, sheet, dims) {
  raw <- read_excel(path, sheet = sheet, col_names = FALSE, col_types = "list",
                    .name_repair = "minimal")
  years <- unlist(lapply(raw[YEAR_ROW, ], function(x) if (is.null(x)) NA else x[[1]]))
  years <- suppressWarnings(as.integer(years))
  # merged year cells: carry the year across its sex columns
  for (j in seq_along(years)) if (j > 1 && is.na(years[j])) years[j] <- years[j - 1]
  sexes <- sub(".*\\((F|M|T)\\)\\s*$", "\\1",
               unlist(lapply(raw[SEX_ROW, ], function(x) if (is.null(x)) "" else as.character(x[[1]]))))
  body <- raw[FIRST_ROW:nrow(raw), ]
  out <- list()
  for (j in FIRST_COL:ncol(raw)) {
    if (is.na(years[j]) || !sexes[j] %in% c("F", "M", "T")) next
    v <- vapply(body[[j]], function(x) if (is.numeric(x)) as.numeric(x) else NA_real_, numeric(1))
    out[[length(out) + 1]] <- tibble(
      d1 = vapply(body[[1]], function(x) as.character(x %||% NA), ""),
      d2 = vapply(body[[3]], function(x) as.character(x %||% NA), ""),
      year = years[j], sex = sexes[j], value = v)
  }
  bind_rows(out) |> filter(!is.na(d1)) |> rename(!!dims[1] := d1, !!dims[2] := d2)
}
`%||%` <- function(a, b) if (is.null(a)) b else a

iso_of <- function(path) {
  cov <- read_excel(path, sheet = "COVER", col_names = FALSE, col_types = "text",
                    .name_repair = "minimal")
  toupper(cov[[3]][which(cov[[1]] == "ISO3")])
}

flags <- list()
for (f in list.files(sub_dir, pattern = "\\.xlsx$", full.names = TRUE)) {
  iso3 <- iso_of(f)
  age <- read_sheet(f, "ENRL_AGE", c("level", "age"))
  grade <- read_sheet(f, "ENRL_GRADE", c("level", "grade"))

  sexsum <- age |>
    pivot_wider(names_from = sex, values_from = value) |>
    filter(!is.na(F), !is.na(M), !is.na(T), F + M != T) |>
    transmute(iso3, rule = "R04_SEX_SUM", level, year)

  agegrade <- inner_join(
    age |> group_by(level, sex, year) |> summarise(by_age = sum(value, na.rm = TRUE), .groups = "drop"),
    grade |> group_by(level, sex, year) |> summarise(by_grade = sum(value, na.rm = TRUE), .groups = "drop"),
    by = c("level", "sex", "year")) |>
    filter(by_age != by_grade) |>
    transmute(iso3, rule = "R05_AGE_GRADE", level, year)

  flags[[iso3]] <- bind_rows(sexsum, agegrade)
}
r_flags <- bind_rows(flags) |> distinct()
cat(sprintf("R found %d flagged (country, rule, level, year) groups\n", nrow(r_flags)))
print(r_flags, n = Inf)

if (file.exists(py_log)) {
  py <- read.csv(py_log) |>
    filter(rule %in% c("R04_SEX_SUM", "R05_AGE_GRADE"), table %in% c("ENRL_AGE", "ENRL_AGE/ENRL_GRADE")) |>
    transmute(iso3, rule, level, year = as.integer(year)) |> distinct()
  only_r <- anti_join(r_flags, py, by = c("iso3", "rule", "level", "year"))
  only_py <- anti_join(py, r_flags, by = c("iso3", "rule", "level", "year"))
  if (nrow(only_r) == 0 && nrow(only_py) == 0) {
    cat("R and Python agree on every age/grade and F+M=T flag.\n")
  } else {
    cat("Disagreements:\n"); print(only_r); print(only_py)
    quit(status = 1)
  }
}
