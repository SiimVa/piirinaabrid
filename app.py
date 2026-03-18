import io

import folium
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

WFS_URL = "https://gsavalik.envir.ee/geoserver/kataster/wfs"
LAYER_NAME = "kataster:ky_kehtiv"
SOURCE_CRS = "EPSG:3301"
MAP_CRS = "EPSG:4326"


def get_feature_by_tunnus(katastritunnus: str) -> gpd.GeoDataFrame:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": LAYER_NAME,
        "outputFormat": "json",
        "srsName": SOURCE_CRS,
        "cql_filter": f"tunnus='{katastritunnus}'",
    }
    response = requests.get(WFS_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    return gpd.GeoDataFrame.from_features(data, crs=SOURCE_CRS)


def get_neighbors(buffer_geom) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = buffer_geom.bounds
    bbox_str = f"{minx},{miny},{maxx},{maxy},{SOURCE_CRS}"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": LAYER_NAME,
        "outputFormat": "json",
        "srsName": SOURCE_CRS,
        "bbox": bbox_str,
    }
    response = requests.get(WFS_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    return gpd.GeoDataFrame.from_features(data, crs=SOURCE_CRS)


def build_map(
    input_parcel: gpd.GeoDataFrame,
    neighbors_gdf: gpd.GeoDataFrame,
    buffer_geom,
) -> folium.Map:
    input_latlon = input_parcel.to_crs(MAP_CRS)
    neighbors_latlon = neighbors_gdf.to_crs(MAP_CRS)
    buffer_gdf = gpd.GeoSeries([buffer_geom], crs=SOURCE_CRS).to_crs(MAP_CRS)

    centroid = input_latlon.geometry.iloc[0].centroid
    parcel_map = folium.Map(location=[centroid.y, centroid.x], zoom_start=14)

    folium.GeoJson(
        data=input_latlon.geometry.iloc[0].__geo_interface__,
        style_function=lambda _: {
            "color": "blue",
            "fillOpacity": 0.1,
            "weight": 2,
        },
        tooltip="Sisendkatastriüksus",
    ).add_to(parcel_map)

    if not neighbors_latlon.empty:
        tooltip_fields = [
            field for field in ["tunnus", "l_aadress", "siht1"]
            if field in neighbors_latlon.columns
        ]
        tooltip_aliases = {
            "tunnus": "Tunnus",
            "l_aadress": "Aadress",
            "siht1": "Sihtotstarve",
        }
        geojson_tooltip = None
        if tooltip_fields:
            geojson_tooltip = folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=[tooltip_aliases[field] for field in tooltip_fields],
                localize=True,
            )

        folium.GeoJson(
            data=neighbors_latlon.__geo_interface__,
            style_function=lambda _: {
                "color": "red",
                "fillOpacity": 0.1,
                "weight": 1,
            },
            tooltip=geojson_tooltip,
        ).add_to(parcel_map)

    folium.GeoJson(
        data=buffer_gdf.__geo_interface__,
        style_function=lambda _: {
            "color": "green",
            "fill": False,
            "weight": 2,
            "dashArray": "5,5",
        },
        tooltip="Puhver",
    ).add_to(parcel_map)

    folium.LayerControl().add_to(parcel_map)
    return parcel_map


def dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    dataframe.to_csv(buffer, index=False, encoding="utf-8-sig", sep=";")
    return buffer.getvalue().encode("utf-8-sig")


st.set_page_config(page_title="Piirinaabrid", layout="wide")
st.title("Piirinaabrite leidja")
st.write("Rakendus leiab valitud katastriüksuse naabrid etteantud puhvri sees.")

with st.sidebar:
    st.header("Sisend")
    katastritunnus = st.text_input(
        "Katastritunnus",
        value="",
        placeholder="Nt 18502:005:0366",
    )
    radius = st.number_input(
        "Raadius meetrites",
        min_value=1,
        max_value=1000,
        value=10,
        step=1,
    )
    search_clicked = st.button("Leia naabrid", type="primary")

if search_clicked:
    try:
        if not katastritunnus.strip():
            st.error("Sisesta katastritunnus.")
            st.stop()

        with st.spinner("Pärin katastriandmeid..."):
            input_parcel = get_feature_by_tunnus(katastritunnus.strip())

        if input_parcel.empty:
            st.error("Selle tunnusega katastriüksust ei leitud.")
            st.stop()

        parcel_geom = input_parcel.geometry.iloc[0]
        buffer_geom = parcel_geom.buffer(radius)

        with st.spinner("Pärin naaberkatastriüksusi..."):
            neighbors_gdf = get_neighbors(buffer_geom)

        neighbors_gdf = neighbors_gdf[neighbors_gdf.geometry.intersects(buffer_geom)]
        neighbors_gdf = neighbors_gdf[neighbors_gdf["tunnus"] != katastritunnus.strip()]

        result_columns = ["tunnus", "l_aadress", "siht1"]
        existing_columns = [col for col in result_columns if col in neighbors_gdf.columns]
        result_df = neighbors_gdf[existing_columns].copy()

        st.subheader("Tulemused")
        st.write(f"Leitud naaberkatastriüksuste arv: **{len(result_df)}**")
        st.dataframe(result_df, use_container_width=True)

        csv_filename = f"{katastritunnus.strip()}_{radius}m.csv"
        st.download_button(
            label="Laadi CSV alla",
            data=dataframe_to_csv_bytes(result_df),
            file_name=csv_filename,
            mime="text/csv",
        )

        st.subheader("Kaart")
        parcel_map = build_map(input_parcel, neighbors_gdf, buffer_geom)
        st_folium(parcel_map, width=None, height=600, use_container_width=True)

    except requests.RequestException as exc:
        st.error(f"Andmepäring ebaõnnestus: {exc}")
    except Exception as exc:
        st.error(f"Tekkis ootamatu viga: {exc}")
else:
    st.info("Sisesta katastritunnus ja vajuta \"Leia naabrid\".")
