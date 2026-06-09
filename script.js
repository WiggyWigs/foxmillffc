const panels = document.querySelectorAll(".panel");
const dots = document.querySelectorAll(".dot");

const observer = new IntersectionObserver(

(entries) => {

    entries.forEach(entry => {

        if (entry.isIntersecting) {

            entry.target.classList.add("visible");

            dots.forEach(dot =>
                dot.classList.remove("active")
            );

            const id = entry.target.id;

            const activeDot =
                document.querySelector(
                    `a[href="#${id}"]`
                );

            if (activeDot) {
                activeDot.classList.add("active");
            }
        }

    });

},

{
    threshold: 0.25
}

);

panels.forEach(panel => {
    observer.observe(panel);
});