        run_pixel_csv("vectors/pixel_vectors.csv");
        run_image_case("random_33x31", 33, 31, 0, "vectors/random_33x31/input_axis32.mem", "vectors/random_33x31/expected_gray.mem");
        run_image_case("random_640x480", 640, 480, 0, "vectors/random_640x480/input_axis32.mem", "vectors/random_640x480/expected_gray.mem");
