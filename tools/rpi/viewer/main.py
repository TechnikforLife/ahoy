import threading
from datetime import datetime

import psutil
from bokeh.models import ColumnDataSource, DatetimeTickFormatter
from bokeh.layouts import column, row
from bokeh.plotting import curdoc, figure

from . import data_generation

# only modify from a Bokeh session callback
source_now = ColumnDataSource(data=dict(x=[], y=[]))
source_today = ColumnDataSource(data=dict(x=[], y=[]))
source_yesterday = ColumnDataSource(data=dict(x=[], y=[]))
source_some_day = ColumnDataSource(data=dict(x=[], y=[]))

# This is important! Save curdoc() to make sure all threads
# see the same document.
doc = curdoc()

p_now = figure(title="Now",
               sizing_mode="stretch_both",
               x_axis_label="x",
               y_axis_label="y")
p_today = figure(title="Today",
                 sizing_mode="stretch_both",
                 x_axis_label="x",
                 y_axis_label="y")
p_yesterday = figure(title="Yesterday",
                     sizing_mode="stretch_both",
                     x_axis_label="x",
                     y_axis_label="y")
p_some_day = figure(title="Some day",
                    sizing_mode="stretch_both",
                    x_axis_label="x",
                    y_axis_label="y")
l_now = p_now.line(x='x', y='y', source=source_now)
l_today = p_today.line(x='x', y='y', source=source_today)
l_yesterday = p_yesterday.line(x='x', y='y', source=source_yesterday)
l_some_day = p_some_day.line(x='x', y='y', source=source_some_day)

p_now.xaxis[0].formatter = DatetimeTickFormatter(hourmin=['%H:%M'], seconds=['%Ss'])
p_today.xaxis[0].formatter = DatetimeTickFormatter(hourmin=['%H:%M'], seconds=['%Ss'])
p_yesterday.xaxis[0].formatter = DatetimeTickFormatter(hourmin=['%H:%M'], seconds=['%Ss'])
p_some_day.xaxis[0].formatter = DatetimeTickFormatter(hourmin=['%H:%M'], seconds=['%Ss'])

r1 = row(p_now, p_today, sizing_mode="stretch_both")
r2 = row(p_some_day, p_yesterday, sizing_mode="stretch_both")
doc.add_root(column(r1, r2, sizing_mode="stretch_both"))

data_generation.the_data.add_doc(doc,
                                 data_generation.MySources(source_now, source_today, source_yesterday, source_some_day))
# doc.add_periodic_callback(internal_task, 2000)
