Post-processing:
=========

Met
-----

+ Temperature /= 100
+ rh /= 1000
+ pressure /= .5
+ wind_vector_north /= 100
+ wind_vector_east /= 100
+ wind_speed /= 100
+ wind_direction /= 100

Normal status flags: {winds true (valid), purge false (off), gps true (good solution)}

State
------

+ Velocity <N, E, D> /= 100
+ Roll angle /= 100
+ Pitch angle /= 100
+ Yaw angle /= 50
+ Airspeed /= 100
+ Vertical winds /= 100
+ Sideslip /= 100
+ AoA, sideslip differential /= 10000